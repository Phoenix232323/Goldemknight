"""Inloggen en uitloggen."""

from __future__ import annotations

from flask import (
    Blueprint,
    current_app,
    redirect,
    render_template,
    request,
    url_for,
)

from ..database import get_db, iso, utcnow
from ..security import (
    csrf_is_valid,
    csrf_token,
    current_user,
    find_user,
    lockout_remaining_minutes,
    login_session,
    logout_session,
    record_login_attempt,
    verify_password,
)

bp = Blueprint("auth", __name__)


def _veilige_vervolgpagina() -> str:
    """Alleen doorsturen binnen dit dashboard, nooit naar een andere site."""
    volgende = request.args.get("volgende", "") or request.form.get("volgende", "")
    if volgende.startswith("/") and not volgende.startswith("//"):
        return volgende
    return url_for("pages.dashboard")


@bp.route("/inloggen", methods=["GET", "POST"])
def login():
    connection = get_db()

    if current_user() is not None:
        return redirect(_veilige_vervolgpagina())

    foutmelding = ""
    gebruikersnaam = ""

    if request.method == "POST":
        gebruikersnaam = (request.form.get("gebruikersnaam") or "").strip()
        wachtwoord = request.form.get("wachtwoord") or ""

        wachttijd = lockout_remaining_minutes(connection)
        if wachttijd:
            foutmelding = (
                f"Te veel mislukte pogingen. Probeer het over {wachttijd} "
                "minuten opnieuw."
            )
        elif not csrf_is_valid():
            foutmelding = "De pagina was verlopen. Probeer het opnieuw."
        else:
            gebruiker = find_user(connection, gebruikersnaam)
            geldig = gebruiker is not None and verify_password(
                gebruiker["password_hash"], wachtwoord
            )
            record_login_attempt(connection, gebruikersnaam, geldig)

            if geldig:
                connection.execute(
                    "UPDATE users SET last_login_at = ? WHERE id = ?",
                    (iso(utcnow()), gebruiker["id"]),
                )
                gebruiker = find_user(connection, gebruikersnaam)
                login_session(gebruiker)
                return redirect(_veilige_vervolgpagina())

            resterend = max(
                0,
                current_app.config["LOGIN_MAX_ATTEMPTS"]
                - _mislukte_pogingen(connection),
            )
            foutmelding = "Gebruikersnaam of wachtwoord klopt niet."
            if resterend:
                foutmelding += f" Nog {resterend} poging(en) over."
            else:
                foutmelding += (
                    " Het inloggen is nu tijdelijk geblokkeerd voor dit apparaat."
                )

    return (
        render_template(
            "login.html",
            foutmelding=foutmelding,
            gebruikersnaam=gebruikersnaam,
            csrf_token=csrf_token(),
            volgende=request.args.get("volgende", ""),
        ),
        401 if foutmelding else 200,
    )


def _mislukte_pogingen(connection) -> int:
    from ..security import failed_attempts_recent

    return failed_attempts_recent(connection)


@bp.route("/uitloggen", methods=["POST", "GET"])
def logout():
    logout_session()
    return redirect(url_for("auth.login"))
