#!/usr/bin/env python3
"""Startpunt van het GoldenKnight dashboard.

Voor even snel testen:      python3 run.py
Voor dagelijks gebruik:     via gunicorn en systemd (zie deploy/ en README.md)
"""

from __future__ import annotations

import os

from app import create_app

app = create_app()


if __name__ == "__main__":
    poort = int(os.environ.get("GK_PORT", 5000))
    host = os.environ.get("GK_HOST", "0.0.0.0")
    debug = os.environ.get("GK_DEBUG", "").lower() in {"1", "true", "ja"}

    print(f"GoldenKnight dashboard draait op http://{host}:{poort}")
    app.run(host=host, port=poort, debug=debug, threaded=True)
