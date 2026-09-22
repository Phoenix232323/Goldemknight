"""Configuratie van het GoldenKnight dashboard.

Alle instellingen komen uit omgevingsvariabelen. Voor de Raspberry Pi is de
makkelijkste manier een ``.env`` bestand naast dit project te zetten; dat wordt
hieronder ingelezen zonder extra dependencies.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_env_file(path: Path) -> None:
    """Leest een eenvoudig KEY=VALUE bestand in os.environ.

    Bestaande omgevingsvariabelen winnen altijd van het bestand, zodat systemd
    of de shell de .env kan overrulen.
    """
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)


_load_env_file(BASE_DIR / ".env")


def _bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "ja", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _secret_key(instance_dir: Path) -> str:
    """Haalt de secret key op, of maakt er eenmalig een aan.

    De key wordt op schijf bewaard zodat sessies een herstart overleven. Het
    bestand krijgt rechten 0600 zodat alleen de service-gebruiker hem kan lezen.
    """
    from_env = os.environ.get("SECRET_KEY")
    if from_env:
        return from_env

    key_file = instance_dir / "secret_key"
    if key_file.is_file():
        stored = key_file.read_text(encoding="utf-8").strip()
        if stored:
            return stored

    generated = secrets.token_hex(32)
    instance_dir.mkdir(parents=True, exist_ok=True)
    key_file.write_text(generated, encoding="utf-8")
    try:
        key_file.chmod(0o600)
    except OSError:  # pragma: no cover - afhankelijk van bestandssysteem
        pass
    return generated


class Config:
    """Instellingen die de Flask-app gebruikt."""

    INSTANCE_DIR = Path(os.environ.get("GK_INSTANCE_DIR", BASE_DIR / "instance"))
    DATABASE_PATH = Path(
        os.environ.get("GK_DATABASE", INSTANCE_DIR / "goldenknight.db")
    )
    UPLOAD_DIR = Path(
        os.environ.get("GK_UPLOAD_DIR", INSTANCE_DIR / "achtergronden")
    )

    SECRET_KEY = _secret_key(INSTANCE_DIR)

    # --- Veiligheid --------------------------------------------------------
    # Zet GK_HTTPS=true zodra het dashboard achter https draait (bijv. nginx
    # met een certificaat). De sessiecookie gaat dan alleen over TLS.
    HTTPS_ONLY = _bool("GK_HTTPS", False)
    SESSION_COOKIE_NAME = "goldenknight_session"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = HTTPS_ONLY
    # Na hoeveel minuten inactiviteit wordt iemand uitgelogd.
    SESSION_IDLE_MINUTES = _int("GK_SESSION_IDLE_MINUTES", 240)
    # Hoeveel mislukte pogingen mag een IP-adres doen voor het op slot gaat.
    LOGIN_MAX_ATTEMPTS = _int("GK_LOGIN_MAX_ATTEMPTS", 5)
    LOGIN_LOCKOUT_MINUTES = _int("GK_LOGIN_LOCKOUT_MINUTES", 15)
    # Standaardaccount dat bij de eerste start wordt aangemaakt.
    DEFAULT_USERNAME = os.environ.get("GK_ADMIN_USER", "admin")
    DEFAULT_PASSWORD = os.environ.get("GK_ADMIN_PASSWORD", "goldenknight")
    # Achter nginx/Caddy? Dan staat het echte IP in X-Forwarded-For.
    TRUST_PROXY_HEADERS = _bool("GK_TRUST_PROXY", False)

    # --- Sensoren ----------------------------------------------------------
    # auto | hardware | simulatie | extern
    SENSOR_SOURCE = os.environ.get("GK_SENSOR_SOURCE", "auto").strip().lower()
    SENSOR_EXTERNAL_URL = os.environ.get("GK_SENSOR_URL", "")
    DHT_PIN = _int("GK_DHT_PIN", 4)
    DHT_TYPE = os.environ.get("GK_DHT_TYPE", "DHT22").strip().upper()
    BH1750_ADDRESS = int(os.environ.get("GK_BH1750_ADDRESS", "0x23"), 16)
    I2C_BUS = _int("GK_I2C_BUS", 1)
    # Hoe vaak een meting in de database wordt gezet (seconden).
    SAMPLE_INTERVAL_SECONDS = _int("GK_SAMPLE_INTERVAL", 60)
    # Hoe lang metingen bewaard blijven. 0 = altijd bewaren.
    HISTORY_RETENTION_DAYS = _int("GK_HISTORY_DAYS", 90)

    # --- Weer --------------------------------------------------------------
    # Open-Meteo is gratis en vraagt geen API-sleutel.
    WEATHER_ENABLED = _bool("GK_WEATHER_ENABLED", True)
    WEATHER_LATITUDE = _float("GK_WEATHER_LAT", 52.3676)
    WEATHER_LONGITUDE = _float("GK_WEATHER_LON", 4.9041)
    WEATHER_PLACE = os.environ.get("GK_WEATHER_PLACE", "Amsterdam")
    WEATHER_CACHE_MINUTES = _int("GK_WEATHER_CACHE_MINUTES", 10)
    WEATHER_TIMEOUT_SECONDS = _int("GK_WEATHER_TIMEOUT", 8)

    # --- Achtergrond -------------------------------------------------------
    MAX_BACKGROUND_BYTES = _int("GK_MAX_BACKGROUND_BYTES", 6 * 1024 * 1024)
    MAX_CONTENT_LENGTH = MAX_BACKGROUND_BYTES + (256 * 1024)

    # --- Overig ------------------------------------------------------------
    # Hoe vaak de browser nieuwe sensordata ophaalt (milliseconden).
    REFRESH_INTERVAL_MS = _int("GK_REFRESH_MS", 2000)
    JSON_SORT_KEYS = False
