"""Achtergrondthread die met vaste tussenpozen een meting wegschrijft.

De webpagina ververst veel vaker dan dit, maar voor de grafieken is eens per
minuut ruim genoeg - en het houdt de SD-kaart van de Pi gezond.
"""

from __future__ import annotations

import logging
import threading

from .database import (
    connect,
    insert_reading,
    prune_login_attempts,
    prune_readings,
)

log = logging.getLogger(__name__)


class SensorSampler:
    def __init__(self, database_path, reader, interval_seconds: int, retention_days: int):
        self._database_path = database_path
        self._reader = reader
        self._interval = max(5, int(interval_seconds))
        self._retention_days = int(retention_days)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._tellen_tot_opschonen = 0

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="sensor-sampler", daemon=True
        )
        self._thread.start()
        log.info("Meetgeschiedenis wordt elke %s seconden bijgewerkt.", self._interval)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        # Meteen één meting, zodat er direct iets in de grafiek staat.
        self._bewaar_meting()
        while not self._stop.wait(self._interval):
            self._bewaar_meting()

    def _bewaar_meting(self) -> None:
        try:
            meting = self._reader.read(use_cache=False)
        except Exception as fout:  # pragma: no cover - hardware-afhankelijk
            log.warning("Meting mislukt: %s", fout)
            return

        if meting.temperature is None and meting.humidity is None and meting.light is None:
            return

        try:
            connection = connect(self._database_path)
        except Exception as fout:
            log.error("Kan de database niet openen: %s", fout)
            return

        try:
            insert_reading(
                connection, meting.temperature, meting.humidity, meting.light
            )
            self._tellen_tot_opschonen += 1
            # Ongeveer eens per etmaal opruimen.
            if self._tellen_tot_opschonen >= max(1, 86400 // self._interval):
                self._tellen_tot_opschonen = 0
                verwijderd = prune_readings(connection, self._retention_days)
                if verwijderd:
                    log.info("%s oude metingen opgeruimd.", verwijderd)
                prune_login_attempts(connection)
        except Exception as fout:
            log.error("Meting opslaan mislukt: %s", fout)
        finally:
            connection.close()
