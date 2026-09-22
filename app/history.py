"""Historische metingen ophalen en samenvatten voor de grafieken.

De database kan duizenden metingen bevatten. Een grafiek van 300 pixels breed
heeft daar niets aan, dus de metingen worden in gelijke tijdvakken gemiddeld.
Dat leest prettiger en houdt de Pi licht belast.
"""

from __future__ import annotations

import sqlite3
from datetime import timedelta

from .database import iso, utcnow

# Naam -> (lengte, aantal punten in de grafiek, label)
PERIODES: dict[str, tuple[timedelta, int, str]] = {
    "1u": (timedelta(hours=1), 60, "Laatste uur"),
    "6u": (timedelta(hours=6), 72, "Laatste 6 uur"),
    "24u": (timedelta(hours=24), 96, "Laatste 24 uur"),
    "7d": (timedelta(days=7), 112, "Laatste 7 dagen"),
    "30d": (timedelta(days=30), 120, "Laatste 30 dagen"),
}

STANDAARD_PERIODE = "24u"

METRIEKEN = [
    {
        "sleutel": "temperature",
        "naam": "Temperatuur",
        "eenheid": "°C",
        "icoon": "\U0001f321️",
        "decimalen": 1,
    },
    {
        "sleutel": "humidity",
        "naam": "Luchtvochtigheid",
        "eenheid": "%",
        "icoon": "\U0001f4a7",
        "decimalen": 1,
    },
    {
        "sleutel": "light",
        "naam": "Licht",
        "eenheid": "",
        "icoon": "\U0001f4a1",
        "decimalen": 0,
    },
]


def _afronden(waarde, decimalen: int):
    if waarde is None:
        return None
    return round(float(waarde), decimalen)


def geschiedenis(
    connection: sqlite3.Connection, periode: str = STANDAARD_PERIODE
) -> dict:
    """Metingen over een periode, gemiddeld per tijdvak."""
    if periode not in PERIODES:
        periode = STANDAARD_PERIODE
    lengte, punten, label = PERIODES[periode]

    seconden_per_vak = max(1, int(lengte.total_seconds() // punten))
    begin = utcnow() - lengte

    # strftime('%s', ts) geeft de unix-tijd; delen door de vakgrootte maakt
    # daar een groepsnummer van. Dat is precies een tijdvak.
    rijen = connection.execute(
        """
        SELECT
            CAST(strftime('%s', ts) AS INTEGER) / ? AS vak,
            AVG(temperature) AS temperature,
            AVG(humidity)    AS humidity,
            AVG(light)       AS light,
            MIN(ts)          AS ts,
            COUNT(*)         AS metingen
        FROM sensor_readings
        WHERE ts >= ?
        GROUP BY vak
        ORDER BY vak ASC
        """,
        (seconden_per_vak, iso(begin)),
    ).fetchall()

    punten_lijst = [
        {
            "tijd": rij["ts"],
            "temperature": _afronden(rij["temperature"], 1),
            "humidity": _afronden(rij["humidity"], 1),
            "light": _afronden(rij["light"], 0),
        }
        for rij in rijen
    ]

    return {
        "periode": periode,
        "label": label,
        "vakgrootte_seconden": seconden_per_vak,
        "aantal": len(punten_lijst),
        "metrieken": METRIEKEN,
        "punten": punten_lijst,
        "samenvatting": _samenvatting(connection, begin),
        "periodes": [
            {"sleutel": sleutel, "label": waarde[2]} for sleutel, waarde in PERIODES.items()
        ],
    }


def _samenvatting(connection: sqlite3.Connection, begin) -> dict:
    """Min/max/gemiddelde per meetwaarde over de gekozen periode."""
    rij = connection.execute(
        """
        SELECT
            MIN(temperature) AS t_min, MAX(temperature) AS t_max, AVG(temperature) AS t_gem,
            MIN(humidity)    AS v_min, MAX(humidity)    AS v_max, AVG(humidity)    AS v_gem,
            MIN(light)       AS l_min, MAX(light)       AS l_max, AVG(light)       AS l_gem,
            COUNT(*)         AS metingen
        FROM sensor_readings
        WHERE ts >= ?
        """,
        (iso(begin),),
    ).fetchone()

    return {
        "metingen": int(rij["metingen"] or 0),
        "temperature": {
            "min": _afronden(rij["t_min"], 1),
            "max": _afronden(rij["t_max"], 1),
            "gemiddelde": _afronden(rij["t_gem"], 1),
        },
        "humidity": {
            "min": _afronden(rij["v_min"], 1),
            "max": _afronden(rij["v_max"], 1),
            "gemiddelde": _afronden(rij["v_gem"], 1),
        },
        "light": {
            "min": _afronden(rij["l_min"], 0),
            "max": _afronden(rij["l_max"], 0),
            "gemiddelde": _afronden(rij["l_gem"], 0),
        },
    }
