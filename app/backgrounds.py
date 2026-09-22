"""Achtergrond van het dashboard: ingebouwde varianten of een eigen foto.

Uploads worden bewust streng gecontroleerd: een dashboard dat plaatjes
accepteert is anders een makkelijke manier om bestanden op de Pi te zetten.
Daarom wordt gekeken naar de grootte, de extensie en de echte inhoud van het
bestand (de 'magic bytes'), en krijgt het bestand een nieuwe, willekeurige naam.
"""

from __future__ import annotations

import secrets
import sqlite3
from pathlib import Path

from .database import get_settings, set_setting

# key -> (naam, css-waarde, is donker)
PRESETS: dict[str, dict] = {
    "nacht": {
        "naam": "Nachtblauw",
        "css": "linear-gradient(160deg, #0d1b2a 0%, #16324f 55%, #1b3a5c 100%)",
        "donker": True,
    },
    "ochtend": {
        "naam": "Zonsopkomst",
        "css": "linear-gradient(160deg, #2b1b3d 0%, #7d3f54 50%, #e08b5a 100%)",
        "donker": True,
    },
    "bos": {
        "naam": "Bosgroen",
        "css": "linear-gradient(160deg, #10241c 0%, #1d4636 55%, #2f6b4f 100%)",
        "donker": True,
    },
    "staal": {
        "naam": "Staalgrijs",
        "css": "linear-gradient(160deg, #1f2226 0%, #33383f 55%, #4a5058 100%)",
        "donker": True,
    },
    "inkt": {
        "naam": "Effen donker",
        "css": "#141414",
        "donker": True,
    },
    "papier": {
        "naam": "Effen licht",
        "css": "linear-gradient(160deg, #f4f4f1 0%, #e6e7e2 100%)",
        "donker": False,
    },
}

STANDAARD_PRESET = "nacht"
THEMAS = {"auto", "licht", "donker"}

SLEUTELS = (
    "achtergrond_type",
    "achtergrond_preset",
    "achtergrond_bestand",
    "achtergrond_vervaging",
    "achtergrond_verduistering",
    "thema",
)

# Toegestane afbeeldingen: extensie -> (mimetype, magic bytes)
TOEGESTAAN = {
    ".png": ("image/png", (b"\x89PNG\r\n\x1a\n",)),
    ".jpg": ("image/jpeg", (b"\xff\xd8\xff",)),
    ".jpeg": ("image/jpeg", (b"\xff\xd8\xff",)),
    ".webp": ("image/webp", (b"RIFF",)),
    ".gif": ("image/gif", (b"GIF87a", b"GIF89a")),
}


def huidige_instellingen(connection: sqlite3.Connection) -> dict:
    opgeslagen = get_settings(connection, SLEUTELS)

    soort = opgeslagen.get("achtergrond_type", "preset")
    if soort not in {"preset", "afbeelding"}:
        soort = "preset"

    preset = opgeslagen.get("achtergrond_preset", STANDAARD_PRESET)
    if preset not in PRESETS:
        preset = STANDAARD_PRESET

    bestand = opgeslagen.get("achtergrond_bestand", "")
    if soort == "afbeelding" and not bestand:
        soort = "preset"

    thema = opgeslagen.get("thema", "auto")
    if thema not in THEMAS:
        thema = "auto"

    return {
        "type": soort,
        "preset": preset,
        "bestand": bestand,
        "vervaging": _getal(opgeslagen.get("achtergrond_vervaging"), 0, 0, 20),
        "verduistering": _getal(opgeslagen.get("achtergrond_verduistering"), 35, 0, 85),
        "thema": thema,
        "presets": [
            {"sleutel": sleutel, "naam": gegevens["naam"], "css": gegevens["css"]}
            for sleutel, gegevens in PRESETS.items()
        ],
    }


def css_achtergrond(instellingen: dict, afbeelding_url: str | None = None) -> str:
    """De CSS-waarde voor background-image."""
    if instellingen["type"] == "afbeelding" and afbeelding_url:
        return f"url('{afbeelding_url}')"
    return PRESETS.get(instellingen["preset"], PRESETS[STANDAARD_PRESET])["css"]


def opslaan(connection: sqlite3.Connection, gegevens: dict) -> dict:
    """Slaat de door de gebruiker gekozen achtergrond op."""
    if "preset" in gegevens:
        preset = str(gegevens["preset"])
        if preset not in PRESETS:
            raise ValueError("Onbekende achtergrond gekozen.")
        set_setting(connection, "achtergrond_preset", preset)
        set_setting(connection, "achtergrond_type", "preset")

    if gegevens.get("type") == "afbeelding":
        if not get_settings(connection, ["achtergrond_bestand"]).get(
            "achtergrond_bestand"
        ):
            raise ValueError("Er is nog geen eigen afbeelding geüpload.")
        set_setting(connection, "achtergrond_type", "afbeelding")

    if "vervaging" in gegevens:
        set_setting(
            connection,
            "achtergrond_vervaging",
            str(_getal(gegevens["vervaging"], 0, 0, 20)),
        )

    if "verduistering" in gegevens:
        set_setting(
            connection,
            "achtergrond_verduistering",
            str(_getal(gegevens["verduistering"], 35, 0, 85)),
        )

    if "thema" in gegevens:
        thema = str(gegevens["thema"])
        if thema not in THEMAS:
            raise ValueError("Onbekend thema gekozen.")
        set_setting(connection, "thema", thema)

    return huidige_instellingen(connection)


def afbeelding_opslaan(
    connection: sqlite3.Connection,
    bestand,
    upload_map: Path,
    maximum_bytes: int,
) -> str:
    """Controleert en bewaart een geüploade achtergrondafbeelding."""
    naam = (getattr(bestand, "filename", "") or "").strip()
    if not naam:
        raise ValueError("Kies eerst een afbeelding.")

    extensie = Path(naam).suffix.lower()
    if extensie not in TOEGESTAAN:
        toegestaan = ", ".join(sorted(TOEGESTAAN))
        raise ValueError(f"Alleen deze bestandstypen kunnen: {toegestaan}.")

    inhoud = bestand.read(maximum_bytes + 1)
    if not inhoud:
        raise ValueError("Het bestand is leeg.")
    if len(inhoud) > maximum_bytes:
        megabytes = maximum_bytes / (1024 * 1024)
        raise ValueError(f"De afbeelding is te groot (maximaal {megabytes:.0f} MB).")

    mimetype, kopteksten = TOEGESTAAN[extensie]
    if not any(inhoud.startswith(kop) for kop in kopteksten):
        raise ValueError(
            "Dit bestand is geen geldige afbeelding, ook al lijkt de naam daar wel op."
        )
    if extensie == ".webp" and inhoud[8:12] != b"WEBP":
        raise ValueError("Dit is geen geldig WebP-bestand.")

    upload_map.mkdir(parents=True, exist_ok=True)
    nieuwe_naam = f"{secrets.token_hex(16)}{extensie}"
    doel = upload_map / nieuwe_naam
    doel.write_bytes(inhoud)
    try:
        doel.chmod(0o640)
    except OSError:  # pragma: no cover - afhankelijk van bestandssysteem
        pass

    vorige = get_settings(connection, ["achtergrond_bestand"]).get(
        "achtergrond_bestand", ""
    )
    set_setting(connection, "achtergrond_bestand", nieuwe_naam)
    set_setting(connection, "achtergrond_type", "afbeelding")
    _verwijder_bestand(upload_map, vorige)

    return nieuwe_naam


def afbeelding_verwijderen(connection: sqlite3.Connection, upload_map: Path) -> None:
    bestand = get_settings(connection, ["achtergrond_bestand"]).get(
        "achtergrond_bestand", ""
    )
    set_setting(connection, "achtergrond_bestand", "")
    set_setting(connection, "achtergrond_type", "preset")
    _verwijder_bestand(upload_map, bestand)


def veilige_bestandsnaam(naam: str) -> str | None:
    """Laat alleen namen toe die deze applicatie zelf heeft gemaakt."""
    if not naam or "/" in naam or "\\" in naam or naam.startswith("."):
        return None
    stam = Path(naam).stem
    extensie = Path(naam).suffix.lower()
    if extensie not in TOEGESTAAN:
        return None
    if len(stam) != 32 or any(teken not in "0123456789abcdef" for teken in stam):
        return None
    return f"{stam}{extensie}"


def mimetype_van(naam: str) -> str:
    return TOEGESTAAN.get(Path(naam).suffix.lower(), ("application/octet-stream",))[0]


def _verwijder_bestand(upload_map: Path, naam: str) -> None:
    veilig = veilige_bestandsnaam(naam or "")
    if not veilig:
        return
    try:
        (upload_map / veilig).unlink(missing_ok=True)
    except OSError:  # pragma: no cover
        pass


def _getal(waarde, standaard: int, minimum: int, maximum: int) -> int:
    try:
        getal = int(float(waarde))
    except (TypeError, ValueError):
        return standaard
    return max(minimum, min(maximum, getal))
