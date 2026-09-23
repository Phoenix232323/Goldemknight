#!/usr/bin/env python3
"""Startpunt van het GoldenKnight dashboard.

Voor even snel testen:      python3 run.py
Voor dagelijks gebruik:     via gunicorn en systemd (zie deploy/ en README.md)

``app.py`` doet precies hetzelfde en start dit bestand op; het is er voor wie
gewend is aan de oude ``python3 app.py``.
"""

from __future__ import annotations

import os

from app import create_app

# Gunicorn en systemd gebruiken deze naam: "run:app".
app = create_app()


def main() -> None:
    poort = int(os.environ.get("GK_PORT", 5000))
    host = os.environ.get("GK_HOST", "0.0.0.0")
    # Debugmodus staat uit: hij toont bij een fout de broncode aan iedereen
    # die de pagina kan openen. Alleen aanzetten terwijl je zelf zit te sleutelen.
    debug = os.environ.get("GK_DEBUG", "").lower() in {"1", "true", "ja"}

    print()
    print("  GoldenKnight Sensor Dashboard")
    print("  -----------------------------")
    print(f"  Open in de browser:   http://<ip-van-je-pi>:{poort}")
    print(f"  Op de Pi zelf:        http://localhost:{poort}")
    print(f"  De ESP32 stuurt naar: http://<ip-van-je-pi>:{poort}/api/sensor")
    print()
    print("  Stoppen doe je met Ctrl + C.")
    print()

    app.run(host=host, port=poort, debug=debug, threaded=True)


if __name__ == "__main__":
    main()
