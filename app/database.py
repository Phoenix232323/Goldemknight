"""SQLite-opslag voor metingen, backlog, instellingen en inlogpogingen.

SQLite is precies goed voor een Raspberry Pi: geen aparte databaseserver, en
met WAL-journaling kan de achtergrondthread schrijven terwijl de webserver
leest.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from flask import current_app, g

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    username          TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    password_hash     TEXT    NOT NULL,
    created_at        TEXT    NOT NULL,
    last_login_at     TEXT,
    must_change_password INTEGER NOT NULL DEFAULT 0,
    session_version   INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS login_attempts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT    NOT NULL,
    username   TEXT    NOT NULL,
    ip_address TEXT    NOT NULL,
    user_agent TEXT    NOT NULL DEFAULT '',
    success    INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_login_attempts_ts ON login_attempts (ts DESC);
CREATE INDEX IF NOT EXISTS idx_login_attempts_ip ON login_attempts (ip_address, ts DESC);

CREATE TABLE IF NOT EXISTS sensor_readings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT    NOT NULL,
    temperature REAL,
    humidity    REAL,
    light       REAL
);
CREATE INDEX IF NOT EXISTS idx_sensor_readings_ts ON sensor_readings (ts DESC);

CREATE TABLE IF NOT EXISTS backlog_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT    NOT NULL,
    description TEXT    NOT NULL DEFAULT '',
    status      TEXT    NOT NULL DEFAULT 'todo',
    priority    TEXT    NOT NULL DEFAULT 'normaal',
    due_date    TEXT,
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL,
    completed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_backlog_status ON backlog_items (status, created_at DESC);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

_init_lock = threading.Lock()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(moment: datetime) -> str:
    """Slaat tijden altijd op als UTC in ISO-formaat (sorteerbaar als tekst)."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed


def connect(database_path: Path | str) -> sqlite3.Connection:
    """Opent een verbinding met de juiste PRAGMA's voor gelijktijdig gebruik."""
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path), timeout=15, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = NORMAL")
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 15000")
    return connection


def get_db() -> sqlite3.Connection:
    """Verbinding voor de huidige request (wordt automatisch gesloten)."""
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE_PATH"])
    return g.db


def close_db(_exception: BaseException | None = None) -> None:
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()


def init_db(database_path: Path | str) -> None:
    """Maakt het schema aan; veilig om meerdere keren te draaien."""
    with _init_lock:
        connection = connect(database_path)
        try:
            connection.executescript(_SCHEMA)
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        finally:
            connection.close()


# --- Instellingen -----------------------------------------------------------

def get_setting(connection: sqlite3.Connection, key: str, default: Any = None) -> Any:
    row = connection.execute(
        "SELECT value FROM settings WHERE key = ?", (key,)
    ).fetchone()
    return row["value"] if row else default


def set_setting(connection: sqlite3.Connection, key: str, value: str) -> None:
    connection.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def get_settings(connection: sqlite3.Connection, keys: Iterable[str]) -> dict[str, str]:
    keys = list(keys)
    if not keys:
        return {}
    placeholders = ",".join("?" for _ in keys)
    rows = connection.execute(
        f"SELECT key, value FROM settings WHERE key IN ({placeholders})", keys
    ).fetchall()
    return {row["key"]: row["value"] for row in rows}


# --- Metingen ---------------------------------------------------------------

def insert_reading(
    connection: sqlite3.Connection,
    temperature: float | None,
    humidity: float | None,
    light: float | None,
    moment: datetime | None = None,
) -> None:
    connection.execute(
        "INSERT INTO sensor_readings (ts, temperature, humidity, light) "
        "VALUES (?, ?, ?, ?)",
        (iso(moment or utcnow()), temperature, humidity, light),
    )


def prune_readings(connection: sqlite3.Connection, retention_days: int) -> int:
    """Gooit oude metingen weg zodat de SD-kaart niet volloopt."""
    if retention_days <= 0:
        return 0
    cutoff = iso(utcnow() - timedelta(days=retention_days))
    cursor = connection.execute(
        "DELETE FROM sensor_readings WHERE ts < ?", (cutoff,)
    )
    return cursor.rowcount or 0


def prune_login_attempts(connection: sqlite3.Connection, retention_days: int = 90) -> int:
    """Houdt het logboek met inlogpogingen beperkt tot de laatste N dagen."""
    if retention_days <= 0:
        return 0
    cutoff = iso(utcnow() - timedelta(days=retention_days))
    cursor = connection.execute(
        "DELETE FROM login_attempts WHERE ts < ?", (cutoff,)
    )
    return cursor.rowcount or 0
