"""JSON-API van het dashboard.

Alles achter /api/ vereist een geldige sessie. Verzoeken die iets wijzigen
moeten bovendien het CSRF-token meesturen in de header X-CSRF-Token.
"""

from __future__ import annotations

import hmac
from datetime import datetime

from flask import Blueprint, current_app, jsonify, request, url_for

from .. import backgrounds, backlog as backlog_module
from ..database import get_db
from ..history import STANDAARD_PERIODE, geschiedenis
from ..security import (
    api_login_required,
    current_user,
    password_problems,
    security_overview,
    set_password,
    verify_password,
)
from ..sensors import BRON_OMSCHRIJVING

bp = Blueprint("api", __name__, url_prefix="/api")


def _fout(melding: str, status: int = 400, code: str = "ongeldig"):
    return jsonify({"error": code, "melding": melding}), status


# --- Sensoren ---------------------------------------------------------------

def _meetwaarde(gegevens: dict, *namen: str):
    """Haalt een getal uit de JSON; accepteert Nederlandse en Engelse namen."""
    for naam in namen:
        if naam not in gegevens:
            continue
        waarde = gegevens[naam]
        if waarde is None or waarde == "":
            return None
        try:
            getal = float(waarde)
        except (TypeError, ValueError):
            return None
        if getal != getal or getal in (float("inf"), float("-inf")):
            return None
        return getal
    return None


@bp.post("/sensor")
def sensor_ontvangen():
    """Ontvangt een meting van de XIAO ESP32-C3.

    Dit is het enige eindpunt zonder login: een microcontroller kan niet
    inloggen. Staat er een GK_SENSOR_TOKEN in .env, dan moet de ESP32 die
    meesturen in de header X-Sensor-Token.
    """
    token = current_app.config.get("SENSOR_TOKEN", "")
    if token:
        meegestuurd = request.headers.get("X-Sensor-Token", "")
        if not hmac.compare_digest(token, meegestuurd):
            current_app.logger.warning(
                "Meting geweigerd: verkeerd sensor-token (van %s).",
                request.remote_addr,
            )
            return _fout("Sensor-token klopt niet.", 401, "token")

    gegevens = request.get_json(silent=True)
    if not isinstance(gegevens, dict):
        return (
            jsonify({"success": False, "message": "Geen JSON-data ontvangen"}),
            400,
        )

    temperatuur = _meetwaarde(gegevens, "temperatuur", "temperature")
    vocht = _meetwaarde(gegevens, "luchtvochtigheid", "humidity", "vochtigheid")
    licht = _meetwaarde(gegevens, "licht", "light")

    if temperatuur is None and vocht is None and licht is None:
        return (
            jsonify(
                {
                    "success": False,
                    "message": (
                        "Geen bruikbare meetwaarden. Verwacht: temperatuur, "
                        "luchtvochtigheid en/of licht."
                    ),
                }
            ),
            400,
        )

    meting = current_app.extensions["sensor_reader"].ontvang(
        temperatuur, vocht, licht
    )
    gemeten = meting.as_dict()

    return jsonify(
        {
            "success": True,
            "message": "Sensordata ontvangen",
            "data": {
                "temperature": gemeten["temperature"],
                "humidity": gemeten["humidity"],
                "light": gemeten["light"],
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            },
        }
    )


@bp.get("/sensor")
@api_login_required
def sensor():
    lezer = current_app.extensions["sensor_reader"]
    meting = lezer.read()
    lokaal = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
    gegevens = meting.as_dict()
    sinds = lezer.seconden_sinds_bericht()
    return jsonify(
        {
            "seconden_sinds_bericht": None if sinds is None else int(sinds),
            # Deze drie velden zijn hetzelfde gebleven als in de eerste versie
            # van het dashboard, zodat bestaande scripts blijven werken.
            "temperature": gegevens["temperature"],
            "humidity": gegevens["humidity"],
            "light": gegevens["light"],
            "timestamp": lokaal,
            "timestamp_iso": gegevens["timestamp"],
            "bron": gegevens["source"],
            "bron_omschrijving": BRON_OMSCHRIJVING.get(
                gegevens["source"], "Sensordata"
            ),
            "live": gegevens["source"] in {"esp32", "hardware", "extern"},
        }
    )


@bp.get("/history")
@api_login_required
def history():
    periode = request.args.get("periode", STANDAARD_PERIODE)
    return jsonify(geschiedenis(get_db(), periode))


# --- Weer -------------------------------------------------------------------

@bp.get("/weer")
@api_login_required
def weer():
    ververs = request.args.get("ververs") == "1"
    return jsonify(current_app.extensions["weather"].get(force=ververs))


# --- Veiligheid -------------------------------------------------------------

@bp.get("/veiligheid")
@api_login_required
def veiligheid():
    return jsonify(security_overview(get_db()))


@bp.post("/wachtwoord")
@api_login_required
def wachtwoord_wijzigen():
    gegevens = request.get_json(silent=True) or {}
    huidig = str(gegevens.get("huidig", ""))
    nieuw = str(gegevens.get("nieuw", ""))
    herhaling = str(gegevens.get("herhaling", ""))

    gebruiker = current_user()
    if not verify_password(gebruiker["password_hash"], huidig):
        return _fout("Het huidige wachtwoord klopt niet.", 403, "wachtwoord")
    if nieuw != herhaling:
        return _fout("De twee nieuwe wachtwoorden zijn niet gelijk.")
    problemen = password_problems(nieuw)
    if problemen:
        return _fout(" ".join(problemen))
    if nieuw == huidig:
        return _fout("Kies een ander wachtwoord dan het huidige.")

    connection = get_db()
    set_password(connection, gebruiker["id"], nieuw)
    return jsonify(
        {
            "ok": True,
            "melding": (
                "Wachtwoord gewijzigd. Je wordt nu uitgelogd; log opnieuw in met "
                "het nieuwe wachtwoord."
            ),
            "opnieuw_inloggen": True,
        }
    )


# --- Backlog ----------------------------------------------------------------

@bp.get("/backlog")
@api_login_required
def backlog_lijst():
    status = request.args.get("status")
    return jsonify(backlog_module.alle_items(get_db(), status))


@bp.post("/backlog")
@api_login_required
def backlog_toevoegen():
    gegevens = request.get_json(silent=True) or {}
    try:
        item = backlog_module.toevoegen(get_db(), gegevens)
    except ValueError as fout:
        return _fout(str(fout))
    return jsonify({"ok": True, "item": item}), 201


@bp.patch("/backlog/<int:item_id>")
@api_login_required
def backlog_bijwerken(item_id: int):
    gegevens = request.get_json(silent=True) or {}
    try:
        item = backlog_module.bijwerken(get_db(), item_id, gegevens)
    except ValueError as fout:
        return _fout(str(fout))
    except LookupError as fout:
        return _fout(str(fout), 404, "niet-gevonden")
    return jsonify({"ok": True, "item": item})


@bp.delete("/backlog/<int:item_id>")
@api_login_required
def backlog_verwijderen(item_id: int):
    try:
        backlog_module.verwijderen(get_db(), item_id)
    except LookupError as fout:
        return _fout(str(fout), 404, "niet-gevonden")
    return jsonify({"ok": True})


@bp.post("/backlog/opruimen")
@api_login_required
def backlog_opruimen():
    aantal = backlog_module.afgeronde_opruimen(get_db())
    return jsonify({"ok": True, "verwijderd": aantal})


# --- Achtergrond ------------------------------------------------------------

def _achtergrond_antwoord(connection) -> dict:
    instellingen = backgrounds.huidige_instellingen(connection)
    afbeelding_url = None
    if instellingen["bestand"]:
        afbeelding_url = url_for(
            "pages.achtergrond_afbeelding", naam=instellingen["bestand"]
        )
    instellingen["afbeelding_url"] = afbeelding_url
    instellingen["css"] = backgrounds.css_achtergrond(instellingen, afbeelding_url)
    return instellingen


@bp.get("/achtergrond")
@api_login_required
def achtergrond_ophalen():
    return jsonify(_achtergrond_antwoord(get_db()))


@bp.post("/achtergrond")
@api_login_required
def achtergrond_opslaan():
    gegevens = request.get_json(silent=True) or {}
    connection = get_db()
    try:
        backgrounds.opslaan(connection, gegevens)
    except ValueError as fout:
        return _fout(str(fout))
    return jsonify({"ok": True, **_achtergrond_antwoord(connection)})


@bp.post("/achtergrond/upload")
@api_login_required
def achtergrond_uploaden():
    bestand = request.files.get("afbeelding")
    if bestand is None:
        return _fout("Er is geen afbeelding meegestuurd.")
    connection = get_db()
    try:
        backgrounds.afbeelding_opslaan(
            connection,
            bestand,
            current_app.config["UPLOAD_DIR"],
            current_app.config["MAX_BACKGROUND_BYTES"],
        )
    except ValueError as fout:
        return _fout(str(fout))
    return jsonify({"ok": True, **_achtergrond_antwoord(connection)})


@bp.delete("/achtergrond/afbeelding")
@api_login_required
def achtergrond_afbeelding_verwijderen():
    connection = get_db()
    backgrounds.afbeelding_verwijderen(connection, current_app.config["UPLOAD_DIR"])
    return jsonify({"ok": True, **_achtergrond_antwoord(connection)})
