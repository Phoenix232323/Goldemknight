"""Weersoverzicht via Open-Meteo (gratis en zonder API-sleutel).

De gegevens worden een paar minuten in het geheugen bewaard, zodat het
dashboard elke seconde kan verversen zonder de weerdienst te belasten. Is het
internet even weg, dan blijft de laatst bekende voorspelling zichtbaar met een
duidelijke melding erbij.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

log = logging.getLogger(__name__)

API_URL = "https://api.open-meteo.com/v1/forecast"

# WMO-weercodes vertaald naar Nederlands.
WEERCODES: dict[int, tuple[str, str]] = {
    0: ("Onbewolkt", "☀️"),
    1: ("Overwegend helder", "\U0001f324️"),
    2: ("Half bewolkt", "⛅"),
    3: ("Bewolkt", "☁️"),
    45: ("Mist", "\U0001f32b️"),
    48: ("Aanvriezende mist", "\U0001f32b️"),
    51: ("Lichte motregen", "\U0001f326️"),
    53: ("Motregen", "\U0001f326️"),
    55: ("Zware motregen", "\U0001f327️"),
    56: ("Lichte ijzel", "\U0001f327️"),
    57: ("IJzel", "\U0001f327️"),
    61: ("Lichte regen", "\U0001f326️"),
    63: ("Regen", "\U0001f327️"),
    65: ("Zware regen", "\U0001f327️"),
    66: ("Lichte ijzelregen", "\U0001f327️"),
    67: ("IJzelregen", "\U0001f327️"),
    71: ("Lichte sneeuw", "\U0001f328️"),
    73: ("Sneeuw", "\U0001f328️"),
    75: ("Zware sneeuw", "❄️"),
    77: ("Sneeuwkorrels", "\U0001f328️"),
    80: ("Lichte buien", "\U0001f326️"),
    81: ("Buien", "\U0001f327️"),
    82: ("Zware buien", "⛈️"),
    85: ("Lichte sneeuwbuien", "\U0001f328️"),
    86: ("Zware sneeuwbuien", "❄️"),
    95: ("Onweer", "⛈️"),
    96: ("Onweer met hagel", "⛈️"),
    99: ("Zwaar onweer met hagel", "⛈️"),
}

WINDRICHTINGEN = [
    "N", "NNO", "NO", "ONO", "O", "OZO", "ZO", "ZZO",
    "Z", "ZZW", "ZW", "WZW", "W", "WNW", "NW", "NNW",
]

DAGEN_KORT = ["ma", "di", "wo", "do", "vr", "za", "zo"]


def omschrijf_weercode(code) -> tuple[str, str]:
    try:
        return WEERCODES[int(code)]
    except (TypeError, ValueError, KeyError):
        return ("Onbekend", "\U0001f321️")


def windrichting(graden) -> str:
    try:
        index = int((float(graden) + 11.25) % 360 // 22.5)
    except (TypeError, ValueError):
        return "-"
    return WINDRICHTINGEN[index]


def _dagnaam(datum_tekst: str) -> str:
    try:
        datum = datetime.strptime(datum_tekst, "%Y-%m-%d")
    except (TypeError, ValueError):
        return datum_tekst
    if datum.date() == datetime.now().date():
        return "vandaag"
    return DAGEN_KORT[datum.weekday()]


def _tijd(tekst: str) -> str:
    try:
        return datetime.fromisoformat(tekst).strftime("%H:%M")
    except (TypeError, ValueError):
        return "-"


class WeatherService:
    """Haalt de voorspelling op en bewaart die kort in het geheugen."""

    def __init__(self, config) -> None:
        self._config = config
        self._lock = threading.Lock()
        self._cache: dict | None = None
        self._cached_at = 0.0

    @property
    def _cache_seconds(self) -> int:
        return max(60, int(self._config.get("WEATHER_CACHE_MINUTES", 10)) * 60)

    def get(self, force: bool = False) -> dict:
        if not self._config.get("WEATHER_ENABLED", True):
            return {
                "beschikbaar": False,
                "melding": "Het weersoverzicht staat uit in de instellingen.",
            }

        with self._lock:
            nu = time.monotonic()
            vers = self._cache is not None and nu - self._cached_at < self._cache_seconds
            if vers and not force:
                return self._cache

            opgehaald = self._fetch()
            if opgehaald is not None:
                self._cache = opgehaald
                self._cached_at = nu
                return opgehaald

            if self._cache is not None:
                verouderd = dict(self._cache)
                verouderd["verouderd"] = True
                verouderd["melding"] = (
                    "Geen verbinding met de weerdienst. Dit is de laatst bekende "
                    "voorspelling."
                )
                return verouderd

            return {
                "beschikbaar": False,
                "melding": (
                    "Het weer kan niet worden opgehaald. Controleer de "
                    "internetverbinding van de Raspberry Pi."
                ),
            }

    def _fetch(self) -> dict | None:
        parameters = {
            "latitude": self._config.get("WEATHER_LATITUDE", 52.3676),
            "longitude": self._config.get("WEATHER_LONGITUDE", 4.9041),
            "timezone": "auto",
            "forecast_days": 5,
            "current": ",".join(
                [
                    "temperature_2m",
                    "apparent_temperature",
                    "relative_humidity_2m",
                    "precipitation",
                    "weather_code",
                    "wind_speed_10m",
                    "wind_direction_10m",
                    "is_day",
                ]
            ),
            "hourly": "temperature_2m,precipitation_probability",
            "daily": ",".join(
                [
                    "weather_code",
                    "temperature_2m_max",
                    "temperature_2m_min",
                    "precipitation_sum",
                    "sunrise",
                    "sunset",
                ]
            ),
        }
        url = f"{API_URL}?{urllib.parse.urlencode(parameters)}"
        timeout = int(self._config.get("WEATHER_TIMEOUT_SECONDS", 8))
        try:
            verzoek = urllib.request.Request(
                url, headers={"User-Agent": "GoldenKnight-Dashboard/1.0"}
            )
            with urllib.request.urlopen(verzoek, timeout=timeout) as antwoord:  # noqa: S310
                ruw = json.loads(antwoord.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError) as fout:
            log.warning("Weer ophalen mislukt: %s", fout)
            return None

        try:
            return self._verwerk(ruw)
        except (KeyError, TypeError, ValueError) as fout:
            log.warning("Onverwacht antwoord van de weerdienst: %s", fout)
            return None

    def _verwerk(self, ruw: dict) -> dict:
        huidig = ruw.get("current", {}) or {}
        dagelijks = ruw.get("daily", {}) or {}
        per_uur = ruw.get("hourly", {}) or {}

        omschrijving, icoon = omschrijf_weercode(huidig.get("weather_code"))

        dagen = []
        datums = dagelijks.get("time", []) or []
        for index, datum in enumerate(datums[:5]):
            dag_omschrijving, dag_icoon = omschrijf_weercode(
                _lijst(dagelijks, "weather_code", index)
            )
            dagen.append(
                {
                    "datum": datum,
                    "dag": _dagnaam(datum),
                    "omschrijving": dag_omschrijving,
                    "icoon": dag_icoon,
                    "max": _lijst(dagelijks, "temperature_2m_max", index),
                    "min": _lijst(dagelijks, "temperature_2m_min", index),
                    "neerslag": _lijst(dagelijks, "precipitation_sum", index),
                }
            )

        # De eerstvolgende 24 uur voor de grafiek in de weerkaart.
        tijden = per_uur.get("time", []) or []
        temperaturen = per_uur.get("temperature_2m", []) or []
        kansen = per_uur.get("precipitation_probability", []) or []
        nu_tekst = str(huidig.get("time", ""))
        start = 0
        for index, tijdstip in enumerate(tijden):
            if tijdstip >= nu_tekst:
                start = index
                break
        uren = [
            {
                "tijd": tijden[i],
                "label": _tijd(tijden[i]),
                "temperatuur": temperaturen[i] if i < len(temperaturen) else None,
                "neerslagkans": kansen[i] if i < len(kansen) else None,
            }
            for i in range(start, min(start + 24, len(tijden)))
        ]

        return {
            "beschikbaar": True,
            "verouderd": False,
            "melding": "",
            "plaats": self._config.get("WEATHER_PLACE", ""),
            "bijgewerkt": huidig.get("time"),
            "nu": {
                "temperatuur": huidig.get("temperature_2m"),
                "gevoel": huidig.get("apparent_temperature"),
                "luchtvochtigheid": huidig.get("relative_humidity_2m"),
                "neerslag": huidig.get("precipitation"),
                "wind": huidig.get("wind_speed_10m"),
                "windrichting": windrichting(huidig.get("wind_direction_10m")),
                "omschrijving": omschrijving,
                "icoon": icoon,
                "is_dag": bool(huidig.get("is_day", 1)),
            },
            "zonsopkomst": _tijd(_lijst(dagelijks, "sunrise", 0) or ""),
            "zonsondergang": _tijd(_lijst(dagelijks, "sunset", 0) or ""),
            "dagen": dagen,
            "uren": uren,
            "eenheden": {
                "temperatuur": "°C",
                "wind": "km/u",
                "neerslag": "mm",
            },
        }


def _lijst(bron: dict, sleutel: str, index: int):
    waarden = bron.get(sleutel) or []
    if index < len(waarden):
        return waarden[index]
    return None
