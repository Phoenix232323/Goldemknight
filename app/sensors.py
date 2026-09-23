"""Waar de meetwaarden vandaan komen.

De gewone manier van werken is de **XIAO ESP32-C3**: die meet temperatuur,
luchtvochtigheid en licht en stuurt ze naar de Pi met een POST naar
``/api/sensor``. De Pi meet dus zelf niets; hij onthoudt alleen het laatste
bericht en schrijft dat weg voor de grafieken.

Hoort de Pi een tijdje niets meer van de ESP32, dan zegt het dashboard dat de
verbinding weg is in plaats van een oude waarde te blijven tonen.

Daarnaast blijven deze bronnen beschikbaar, voor het geval er ooit iets
rechtstreeks aan de Pi komt te hangen:

* DHT11 / DHT22 (temperatuur + luchtvochtigheid) via ``adafruit-circuitpython-dht``
* BH1750 lichtsensor via I2C (``smbus2``)
* LDR via een MCP3008 A/D-omzetter op SPI (``spidev``)
* een externe JSON-service (``GK_SENSOR_SOURCE=extern``)
* een simulatiemodus met realistische nepdata, om zonder hardware te testen
"""

from __future__ import annotations

import json
import logging
import math
import random
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, asdict
from datetime import datetime, timezone

log = logging.getLogger(__name__)


@dataclass
class Reading:
    temperature: float | None
    humidity: float | None
    light: float | None
    source: str
    timestamp: datetime

    def as_dict(self) -> dict:
        data = asdict(self)
        data["timestamp"] = self.timestamp.astimezone(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        return data


def _round(value: float | None, digits: int = 1) -> float | None:
    if value is None:
        return None
    try:
        rounded = round(float(value), digits)
    except (TypeError, ValueError):
        return None
    if math.isnan(rounded) or math.isinf(rounded):
        return None
    return rounded


class _Simulator:
    """Zachte, geloofwaardige nepdata (random walk rond een dagritme)."""

    def __init__(self) -> None:
        self._temperature = 21.0
        self._humidity = 48.0

    def read(self) -> tuple[float, float, float]:
        now = datetime.now()
        # Een dagcurve: 's nachts koeler en donkerder, overdag warmer.
        uur = now.hour + now.minute / 60
        dag = math.sin((uur - 9) / 24 * 2 * math.pi)

        self._temperature += random.uniform(-0.08, 0.08)
        self._temperature = max(15.0, min(28.0, self._temperature))
        temperatuur = self._temperature + dag * 1.8

        self._humidity += random.uniform(-0.4, 0.4)
        self._humidity = max(30.0, min(75.0, self._humidity))
        vocht = self._humidity - dag * 4

        licht = max(0.0, 420 * max(0.0, dag) + random.uniform(0, 25))
        return temperatuur, vocht, licht


class SensorReader:
    """Leest de sensoren uit; thread-safe en met een korte cache.

    De DHT22 mag maar eens per twee seconden gelezen worden, en een mislukte
    meting is bij dit type sensor heel normaal. Daarom wordt de laatste geldige
    waarde kort vastgehouden.
    """

    def __init__(self, config) -> None:
        self._config = config
        self._lock = threading.Lock()
        self._simulator = _Simulator()
        self._cache: Reading | None = None
        self._cache_seconds = 2.0
        self._cached_at = 0.0
        self._dht = None
        self._dht_failed = False
        self._i2c_bus = None
        self._i2c_failed = False
        self._spi = None
        self._spi_failed = False

        self._laatste_bericht: Reading | None = None
        self._bericht_ontvangen_op = 0.0

        bron = str(config.get("SENSOR_SOURCE", "esp32")).lower()
        if bron in {"push", "esp32-c3", "xiao"}:
            bron = "esp32"
        if bron not in {"esp32", "auto", "hardware", "simulatie", "extern"}:
            log.warning("Onbekende GK_SENSOR_SOURCE '%s', val terug op 'esp32'.", bron)
            bron = "esp32"
        self.source_mode = bron

    # --- Hardware ----------------------------------------------------------

    def _read_dht(self) -> tuple[float | None, float | None]:
        if self._dht_failed:
            return None, None
        if self._dht is None:
            try:
                import adafruit_dht  # type: ignore
                import board  # type: ignore

                pin_nummer = int(self._config.get("DHT_PIN", 4))
                pin = getattr(board, f"D{pin_nummer}")
                soort = str(self._config.get("DHT_TYPE", "DHT22")).upper()
                klasse = adafruit_dht.DHT11 if soort == "DHT11" else adafruit_dht.DHT22
                self._dht = klasse(pin, use_pulseio=False)
                log.info("%s gevonden op GPIO %s.", soort, pin_nummer)
            except Exception as fout:  # pragma: no cover - hardware-afhankelijk
                log.info("Geen DHT-sensor beschikbaar (%s).", fout)
                self._dht_failed = True
                return None, None

        try:  # pragma: no cover - hardware-afhankelijk
            return self._dht.temperature, self._dht.humidity
        except RuntimeError:
            # Een enkele mislukte meting hoort bij de DHT: gewoon overslaan.
            return None, None
        except Exception as fout:
            log.warning("DHT-sensor gaf een fout: %s", fout)
            return None, None

    def _read_bh1750(self) -> float | None:
        if self._i2c_failed:
            return None
        if self._i2c_bus is None:
            try:
                from smbus2 import SMBus  # type: ignore

                self._i2c_bus = SMBus(int(self._config.get("I2C_BUS", 1)))
                log.info("BH1750 lichtsensor gevonden op I2C.")
            except Exception as fout:  # pragma: no cover - hardware-afhankelijk
                log.info("Geen I2C-lichtsensor beschikbaar (%s).", fout)
                self._i2c_failed = True
                return None

        try:  # pragma: no cover - hardware-afhankelijk
            adres = int(self._config.get("BH1750_ADDRESS", 0x23))
            # 0x20 = eenmalige meting in hoge resolutie.
            data = self._i2c_bus.read_i2c_block_data(adres, 0x20, 2)
            return ((data[0] << 8) | data[1]) / 1.2
        except Exception as fout:
            log.warning("Lichtsensor gaf een fout: %s", fout)
            return None

    def _read_mcp3008(self) -> float | None:
        """LDR op kanaal 0 van een MCP3008, omgerekend naar 0-100%."""
        if self._spi_failed:
            return None
        if self._spi is None:
            try:
                import spidev  # type: ignore

                self._spi = spidev.SpiDev()
                self._spi.open(0, 0)
                self._spi.max_speed_hz = 1_350_000
                log.info("MCP3008 gevonden op SPI0.")
            except Exception as fout:  # pragma: no cover - hardware-afhankelijk
                log.info("Geen MCP3008 beschikbaar (%s).", fout)
                self._spi_failed = True
                return None

        try:  # pragma: no cover - hardware-afhankelijk
            antwoord = self._spi.xfer2([1, 0x80, 0])
            ruw = ((antwoord[1] & 3) << 8) + antwoord[2]
            return ruw / 1023 * 100
        except Exception as fout:
            log.warning("MCP3008 gaf een fout: %s", fout)
            return None

    def _read_external(self) -> Reading | None:
        """Haalt data op bij een eigen sensorservice die JSON teruggeeft."""
        url = str(self._config.get("SENSOR_EXTERNAL_URL", "")).strip()
        if not url:
            return None
        if not url.startswith(("http://", "https://")):
            log.warning("GK_SENSOR_URL moet met http:// of https:// beginnen.")
            return None
        try:
            with urllib.request.urlopen(url, timeout=5) as antwoord:  # noqa: S310
                data = json.loads(antwoord.read().decode("utf-8"))
        except (urllib.error.URLError, ValueError, OSError) as fout:
            log.warning("Externe sensorservice niet bereikbaar: %s", fout)
            return None
        if not isinstance(data, dict):
            return None
        return Reading(
            temperature=_round(data.get("temperature")),
            humidity=_round(data.get("humidity")),
            light=_round(data.get("light")),
            source="extern",
            timestamp=datetime.now(timezone.utc),
        )

    # --- Berichten van de ESP32 -------------------------------------------

    def ontvang(
        self,
        temperature: float | None,
        humidity: float | None,
        light: float | None,
    ) -> Reading:
        """Neemt een meting aan die de ESP32-C3 heeft opgestuurd."""
        meting = Reading(
            temperature=_round(temperature),
            humidity=_round(humidity),
            light=_round(light, 0),
            source="esp32",
            timestamp=datetime.now(timezone.utc),
        )
        with self._lock:
            self._laatste_bericht = meting
            self._bericht_ontvangen_op = time.monotonic()
            # De cache mag niet in de weg zitten: dit is verse data.
            self._cache = meting
            self._cached_at = self._bericht_ontvangen_op
        return meting

    @property
    def _max_leeftijd(self) -> float:
        return max(5, int(self._config.get("SENSOR_MAX_AGE_SECONDS", 120)))

    def _bericht_indien_vers(self) -> Reading | None:
        if self._laatste_bericht is None:
            return None
        if time.monotonic() - self._bericht_ontvangen_op > self._max_leeftijd:
            return None
        return self._laatste_bericht

    def seconden_sinds_bericht(self) -> float | None:
        """Hoe lang geleden de ESP32 voor het laatst iets stuurde."""
        with self._lock:
            if self._laatste_bericht is None:
                return None
            return time.monotonic() - self._bericht_ontvangen_op

    # --- Publieke API ------------------------------------------------------

    def read(self, use_cache: bool = True) -> Reading:
        with self._lock:
            # Bij de ESP32 hoeft er niets uitgelezen te worden: het laatste
            # bericht staat al klaar in het geheugen.
            if self.source_mode in {"esp32", "auto"}:
                vers = self._bericht_indien_vers()
                if vers is not None:
                    return vers
                if self.source_mode == "esp32":
                    return Reading(
                        None, None, None, "esp32-offline",
                        datetime.now(timezone.utc),
                    )

            nu = time.monotonic()
            if (
                use_cache
                and self._cache is not None
                and nu - self._cached_at < self._cache_seconds
            ):
                return self._cache

            meting = self._read_now()
            self._cache = meting
            self._cached_at = nu
            return meting

    def _read_now(self) -> Reading:
        tijd = datetime.now(timezone.utc)

        if self.source_mode == "simulatie":
            temperatuur, vocht, licht = self._simulator.read()
            return Reading(
                _round(temperatuur), _round(vocht), _round(licht, 0), "simulatie", tijd
            )

        if self.source_mode == "extern":
            extern = self._read_external()
            if extern is not None:
                return extern
            return Reading(None, None, None, "extern-offline", tijd)

        temperatuur, vocht = self._read_dht()
        licht = self._read_bh1750()
        if licht is None:
            licht = self._read_mcp3008()

        if temperatuur is None and vocht is None and licht is None:
            if self.source_mode == "hardware":
                # Expliciet hardware gekozen: geen nepdata verzinnen.
                return Reading(None, None, None, "hardware-offline", tijd)
            temperatuur, vocht, licht = self._simulator.read()
            return Reading(
                _round(temperatuur), _round(vocht), _round(licht, 0), "simulatie", tijd
            )

        return Reading(
            _round(temperatuur), _round(vocht), _round(licht, 0), "hardware", tijd
        )

    def close(self) -> None:  # pragma: no cover - hardware-afhankelijk
        for onderdeel in (self._dht, self._i2c_bus, self._spi):
            try:
                if onderdeel is not None and hasattr(onderdeel, "close"):
                    onderdeel.close()
            except Exception:
                pass


BRON_OMSCHRIJVING = {
    "esp32": "Live sensordata van de XIAO ESP32-C3",
    "esp32-offline": "Geen bericht van de XIAO ESP32-C3",
    "hardware": "Live sensordata",
    "simulatie": "Simulatiemodus - geen sensor gevonden",
    "extern": "Live sensordata via externe service",
    "extern-offline": "Externe sensorservice niet bereikbaar",
    "hardware-offline": "Sensor niet bereikbaar",
}
