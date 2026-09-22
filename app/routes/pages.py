"""De pagina's van het dashboard."""

from __future__ import annotations

from flask import (
    Blueprint,
    abort,
    current_app,
    send_from_directory,
    render_template,
    url_for,
)

from .. import __version__
from ..backgrounds import (
    css_achtergrond,
    huidige_instellingen,
    mimetype_van,
    veilige_bestandsnaam,
)
from ..backlog import PRIORITEITEN, STATUSSEN
from ..database import get_db
from ..history import METRIEKEN, PERIODES, STANDAARD_PERIODE
from ..security import csrf_token, current_user, login_required

bp = Blueprint("pages", __name__)


@bp.route("/")
@login_required
def dashboard():
    connection = get_db()
    achtergrond = huidige_instellingen(connection)

    afbeelding_url = None
    if achtergrond["type"] == "afbeelding" and achtergrond["bestand"]:
        afbeelding_url = url_for(
            "pages.achtergrond_afbeelding", naam=achtergrond["bestand"]
        )

    gebruiker = current_user()

    return render_template(
        "dashboard.html",
        gebruiker=gebruiker["username"],
        wachtwoord_verlopen=bool(gebruiker["must_change_password"]),
        csrf_token=csrf_token(),
        versie=__version__,
        achtergrond=achtergrond,
        achtergrond_css=css_achtergrond(achtergrond, afbeelding_url),
        achtergrond_url=afbeelding_url,
        achtergrond_vervaging=achtergrond["vervaging"],
        achtergrond_verduistering=achtergrond["verduistering"],
        thema=achtergrond["thema"],
        ververs_ms=current_app.config["REFRESH_INTERVAL_MS"],
        metrieken=METRIEKEN,
        periodes=[
            {"sleutel": sleutel, "label": waarde[2]}
            for sleutel, waarde in PERIODES.items()
        ],
        standaard_periode=STANDAARD_PERIODE,
        statussen=[
            {"sleutel": sleutel, "naam": waarde["naam"]}
            for sleutel, waarde in STATUSSEN.items()
        ],
        prioriteiten=[
            {"sleutel": sleutel, "naam": waarde["naam"]}
            for sleutel, waarde in PRIORITEITEN.items()
        ],
        weer_aan=current_app.config["WEATHER_ENABLED"],
        weer_plaats=current_app.config["WEATHER_PLACE"],
    )


@bp.route("/achtergrond/afbeelding/<naam>")
@login_required
def achtergrond_afbeelding(naam: str):
    veilig = veilige_bestandsnaam(naam)
    if not veilig:
        abort(404)
    map_pad = current_app.config["UPLOAD_DIR"]
    if not (map_pad / veilig).is_file():
        abort(404)
    antwoord = send_from_directory(
        map_pad, veilig, mimetype=mimetype_van(veilig), max_age=3600
    )
    antwoord.headers["Cache-Control"] = "private, max-age=3600"
    return antwoord


@bp.route("/gezondheid")
def gezondheid():
    """Simpel eindpunt om te controleren of de service draait."""
    return {"status": "ok", "versie": __version__}


@bp.app_errorhandler(404)
def niet_gevonden(_fout):
    return render_template("fout.html", code=404, melding="Deze pagina bestaat niet."), 404


@bp.app_errorhandler(413)
def te_groot(_fout):
    return (
        render_template(
            "fout.html", code=413, melding="Het verstuurde bestand is te groot."
        ),
        413,
    )


@bp.app_errorhandler(500)
def serverfout(_fout):
    return (
        render_template(
            "fout.html",
            code=500,
            melding="Er ging iets mis op de server. Kijk in het logboek van de service.",
        ),
        500,
    )
