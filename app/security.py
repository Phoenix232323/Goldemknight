"""Alles rond veiligheid: inloggen, CSRF, bruteforce-bescherming en headers.

Een dashboard op een Raspberry Pi hangt vaak aan het thuisnetwerk (en soms via
port-forwarding aan het internet). Daarom staat hier:

* wachtwoorden als hash (nooit in platte tekst)
* een sessiecookie met HttpOnly/SameSite, en Secure zodra https aanstaat
* CSRF-tokens voor alles wat data verandert
* een slot op het inlogscherm na te veel mislukte pogingen
* beveiligingsheaders (CSP, nosniff, frame-deny, referrer-policy)
* een logboek van inlogpogingen dat je op het dashboard terugziet
"""

from __future__ import annotations

import functools
import hmac
import secrets
import sqlite3
from datetime import timedelta

from flask import (
    current_app,
    g,
    jsonify,
    redirect,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from .database import get_db, iso, parse_iso, utcnow

SESSION_USER_ID = "user_id"
SESSION_USERNAME = "username"
SESSION_VERSION = "session_version"
SESSION_LAST_SEEN = "last_seen"
SESSION_CSRF = "csrf_token"


# --- Wachtwoorden -----------------------------------------------------------

def hash_password(password: str) -> str:
    return generate_password_hash(password, method="pbkdf2:sha256:260000")


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return check_password_hash(password_hash, password)
    except (ValueError, TypeError):
        return False


def password_problems(password: str) -> list[str]:
    """Minimale eisen aan een wachtwoord, in gewone taal."""
    problems: list[str] = []
    if len(password) < 10:
        problems.append("Gebruik minimaal 10 tekens.")
    if password.isdigit():
        problems.append("Gebruik niet alleen cijfers.")
    if password.lower() in {"goldenknight", "raspberry", "wachtwoord", "password"}:
        problems.append("Dit wachtwoord is te makkelijk te raden.")
    return problems


# --- Gebruikers -------------------------------------------------------------

def find_user(connection: sqlite3.Connection, username: str) -> sqlite3.Row | None:
    return connection.execute(
        "SELECT * FROM users WHERE username = ?", (username.strip(),)
    ).fetchone()


def get_user_by_id(connection: sqlite3.Connection, user_id: int) -> sqlite3.Row | None:
    return connection.execute(
        "SELECT * FROM users WHERE id = ?", (user_id,)
    ).fetchone()


def create_user(
    connection: sqlite3.Connection,
    username: str,
    password: str,
    must_change_password: bool = False,
) -> int:
    cursor = connection.execute(
        "INSERT INTO users (username, password_hash, created_at, must_change_password) "
        "VALUES (?, ?, ?, ?)",
        (
            username.strip(),
            hash_password(password),
            iso(utcnow()),
            1 if must_change_password else 0,
        ),
    )
    return int(cursor.lastrowid)


def set_password(connection: sqlite3.Connection, user_id: int, password: str) -> None:
    """Nieuw wachtwoord zetten en alle bestaande sessies ongeldig maken."""
    connection.execute(
        "UPDATE users SET password_hash = ?, must_change_password = 0, "
        "session_version = session_version + 1 WHERE id = ?",
        (hash_password(password), user_id),
    )


def ensure_default_user(connection: sqlite3.Connection) -> None:
    """Maakt bij de allereerste start één beheerdersaccount aan."""
    row = connection.execute("SELECT COUNT(*) AS aantal FROM users").fetchone()
    if row["aantal"]:
        return
    create_user(
        connection,
        current_app.config["DEFAULT_USERNAME"],
        current_app.config["DEFAULT_PASSWORD"],
        must_change_password=True,
    )
    current_app.logger.warning(
        "Standaardaccount '%s' aangemaakt. Verander het wachtwoord direct na "
        "de eerste keer inloggen.",
        current_app.config["DEFAULT_USERNAME"],
    )


# --- Inlogpogingen en bruteforce-slot ---------------------------------------

def client_ip() -> str:
    """Het IP van de bezoeker, ook als er een reverse proxy voor staat."""
    if current_app.config.get("TRUST_PROXY_HEADERS"):
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            return forwarded.split(",")[0].strip()[:64]
    return (request.remote_addr or "onbekend")[:64]


def record_login_attempt(
    connection: sqlite3.Connection, username: str, success: bool
) -> None:
    connection.execute(
        "INSERT INTO login_attempts (ts, username, ip_address, user_agent, success) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            iso(utcnow()),
            (username or "")[:64],
            client_ip(),
            (request.user_agent.string or "")[:200],
            1 if success else 0,
        ),
    )


def _telpunt(connection: sqlite3.Connection, ip: str) -> str:
    """Vanaf welk moment mislukte pogingen meetellen voor het slot.

    Dat is het begin van de lockout-periode, of - als dat later is - de laatste
    geslaagde login vanaf dit IP. Zo telt het slot na een goede login opnieuw
    vanaf nul, terwijl het logboek met inlogpogingen gewoon bewaard blijft.
    Dat logboek is juist het bewijsmateriaal op de kaart 'Veiligheid'.
    """
    minutes = current_app.config["LOGIN_LOCKOUT_MINUTES"]
    vanaf = iso(utcnow() - timedelta(minutes=minutes))
    rij = connection.execute(
        "SELECT ts FROM login_attempts WHERE ip_address = ? AND success = 1 "
        "ORDER BY ts DESC LIMIT 1",
        (ip,),
    ).fetchone()
    if rij and rij["ts"] > vanaf:
        return rij["ts"]
    return vanaf


def failed_attempts_recent(connection: sqlite3.Connection) -> int:
    """Aantal mislukte pogingen dat meetelt voor het slot op dit IP."""
    ip = client_ip()
    rij = connection.execute(
        "SELECT COUNT(*) AS aantal FROM login_attempts "
        "WHERE ip_address = ? AND success = 0 AND ts >= ?",
        (ip, _telpunt(connection, ip)),
    ).fetchone()
    return int(rij["aantal"])


def lockout_remaining_minutes(connection: sqlite3.Connection) -> int:
    """Hoeveel minuten dit IP nog moet wachten. 0 = niet geblokkeerd."""
    maximum = current_app.config["LOGIN_MAX_ATTEMPTS"]
    minutes = current_app.config["LOGIN_LOCKOUT_MINUTES"]
    if maximum <= 0 or failed_attempts_recent(connection) < maximum:
        return 0

    ip = client_ip()
    rij = connection.execute(
        "SELECT ts FROM login_attempts WHERE ip_address = ? AND success = 0 "
        "AND ts >= ? ORDER BY ts DESC LIMIT 1",
        (ip, _telpunt(connection, ip)),
    ).fetchone()
    if not rij:
        return 0
    laatste = parse_iso(rij["ts"])
    if laatste is None:
        return 0
    open_om = laatste + timedelta(minutes=minutes)
    resterend = (open_om - utcnow()).total_seconds() / 60
    return max(0, int(resterend) + 1)


# --- Sessies ----------------------------------------------------------------

def login_session(user: sqlite3.Row) -> None:
    session.clear()
    session[SESSION_USER_ID] = user["id"]
    session[SESSION_USERNAME] = user["username"]
    session[SESSION_VERSION] = user["session_version"]
    session[SESSION_LAST_SEEN] = iso(utcnow())
    session[SESSION_CSRF] = secrets.token_urlsafe(32)
    session.permanent = True


def logout_session() -> None:
    session.clear()


def current_user() -> sqlite3.Row | None:
    """De ingelogde gebruiker, of None. Controleert ook de sessie-geldigheid."""
    if "current_user" in g:
        return g.current_user

    g.current_user = None
    user_id = session.get(SESSION_USER_ID)
    if not user_id:
        return None

    last_seen = parse_iso(session.get(SESSION_LAST_SEEN, ""))
    idle_minutes = current_app.config["SESSION_IDLE_MINUTES"]
    if last_seen is None or utcnow() - last_seen > timedelta(minutes=idle_minutes):
        logout_session()
        return None

    user = get_user_by_id(get_db(), user_id)
    if user is None or user["session_version"] != session.get(SESSION_VERSION):
        # Wachtwoord gewijzigd of account verwijderd: sessie is niet meer geldig.
        logout_session()
        return None

    session[SESSION_LAST_SEEN] = iso(utcnow())
    g.current_user = user
    return user


def csrf_token() -> str:
    token = session.get(SESSION_CSRF)
    if not token:
        token = secrets.token_urlsafe(32)
        session[SESSION_CSRF] = token
    return token


def csrf_is_valid() -> bool:
    expected = session.get(SESSION_CSRF, "")
    provided = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token", "")
    if not expected or not provided:
        return False
    return hmac.compare_digest(expected, provided)


# --- Decorators -------------------------------------------------------------

def login_required(view):
    """Pagina's: stuur naar het inlogscherm als je niet ingelogd bent."""

    @functools.wraps(view)
    def wrapper(*args, **kwargs):
        if current_user() is None:
            return redirect(url_for("auth.login", volgende=request.path))
        return view(*args, **kwargs)

    return wrapper


def api_login_required(view):
    """API: geef nette JSON terug in plaats van een redirect."""

    @functools.wraps(view)
    def wrapper(*args, **kwargs):
        if current_user() is None:
            return jsonify({"error": "niet-ingelogd", "melding": "Log opnieuw in."}), 401
        if request.method not in {"GET", "HEAD", "OPTIONS"} and not csrf_is_valid():
            return (
                jsonify(
                    {
                        "error": "csrf",
                        "melding": "Beveiligingstoken ongeldig, herlaad de pagina.",
                    }
                ),
                403,
            )
        return view(*args, **kwargs)

    return wrapper


# --- Response headers -------------------------------------------------------

CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'; "
    "img-src 'self' data: blob:; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "connect-src 'self'; "
    "object-src 'none'"
)


def apply_security_headers(response):
    response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault(
        "Permissions-Policy", "geolocation=(), microphone=(), camera=()"
    )
    response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    if current_app.config.get("HTTPS_ONLY"):
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


# --- Veiligheidsoverzicht voor het dashboard --------------------------------

def security_overview(connection: sqlite3.Connection) -> dict:
    """Bouwt de gegevens voor de kaart 'Veiligheid' op het dashboard."""
    user = current_user()
    config = current_app.config

    recent = connection.execute(
        "SELECT ts, username, ip_address, success FROM login_attempts "
        "ORDER BY ts DESC LIMIT 10"
    ).fetchall()

    since_24h = iso(utcnow() - timedelta(hours=24))
    mislukt_24h = connection.execute(
        "SELECT COUNT(*) AS aantal FROM login_attempts WHERE success = 0 AND ts >= ?",
        (since_24h,),
    ).fetchone()["aantal"]
    gelukt_24h = connection.execute(
        "SELECT COUNT(*) AS aantal FROM login_attempts WHERE success = 1 AND ts >= ?",
        (since_24h,),
    ).fetchone()["aantal"]

    standaard_wachtwoord = False
    if user is not None:
        standaard_wachtwoord = bool(user["must_change_password"]) or verify_password(
            user["password_hash"], config["DEFAULT_PASSWORD"]
        )

    controles = [
        {
            "naam": "Wachtwoord aangepast",
            "ok": not standaard_wachtwoord,
            "uitleg": (
                "Het standaardwachtwoord is nog actief. Verander het bij "
                "Instellingen."
                if standaard_wachtwoord
                else "Er is een eigen wachtwoord ingesteld."
            ),
        },
        {
            "naam": "Versleutelde verbinding (https)",
            "ok": bool(config.get("HTTPS_ONLY")),
            "uitleg": (
                "Actief: de sessiecookie gaat alleen over https."
                if config.get("HTTPS_ONLY")
                else "Alleen http. Prima binnen je eigen netwerk; zet https aan "
                "zodra het dashboard van buitenaf bereikbaar is."
            ),
        },
        {
            "naam": "Debugmodus uit",
            "ok": not current_app.debug,
            "uitleg": (
                "Debugmodus staat aan. Zet die uit op een Pi die anderen kunnen "
                "bereiken."
                if current_app.debug
                else "Debugmodus staat uit."
            ),
        },
        {
            "naam": "Eigen sleutel ingesteld",
            "ok": len(str(config.get("SECRET_KEY", ""))) >= 32,
            "uitleg": "De sessies worden ondertekend met een unieke sleutel.",
        },
        {
            "naam": "Bruteforce-slot actief",
            "ok": config["LOGIN_MAX_ATTEMPTS"] > 0,
            "uitleg": (
                f"Na {config['LOGIN_MAX_ATTEMPTS']} mislukte pogingen is het "
                f"inloggen {config['LOGIN_LOCKOUT_MINUTES']} minuten geblokkeerd."
            ),
        },
    ]

    return {
        "gebruiker": user["username"] if user is not None else None,
        "laatste_login": (user["last_login_at"] if user is not None else None),
        "sessie_verloopt_na_minuten": config["SESSION_IDLE_MINUTES"],
        "mislukt_24u": int(mislukt_24h),
        "gelukt_24u": int(gelukt_24h),
        "score": sum(1 for c in controles if c["ok"]),
        "score_max": len(controles),
        "controles": controles,
        "pogingen": [
            {
                "tijd": row["ts"],
                "gebruiker": row["username"],
                "ip": row["ip_address"],
                "gelukt": bool(row["success"]),
            }
            for row in recent
        ],
    }
