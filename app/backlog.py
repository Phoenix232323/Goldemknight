"""Backlog: een eenvoudige takenlijst voor het project op de Raspberry Pi."""

from __future__ import annotations

import sqlite3

from .database import iso, utcnow

STATUSSEN = {
    "todo": {"naam": "Te doen", "volgorde": 0},
    "bezig": {"naam": "Mee bezig", "volgorde": 1},
    "klaar": {"naam": "Klaar", "volgorde": 2},
}

PRIORITEITEN = {
    "hoog": {"naam": "Hoog", "volgorde": 0},
    "normaal": {"naam": "Normaal", "volgorde": 1},
    "laag": {"naam": "Laag", "volgorde": 2},
}

MAX_TITEL = 160
MAX_OMSCHRIJVING = 2000


def _rij_naar_item(rij: sqlite3.Row) -> dict:
    return {
        "id": rij["id"],
        "titel": rij["title"],
        "omschrijving": rij["description"],
        "status": rij["status"],
        "status_naam": STATUSSEN.get(rij["status"], {}).get("naam", rij["status"]),
        "prioriteit": rij["priority"],
        "prioriteit_naam": PRIORITEITEN.get(rij["priority"], {}).get(
            "naam", rij["priority"]
        ),
        "deadline": rij["due_date"],
        "aangemaakt": rij["created_at"],
        "bijgewerkt": rij["updated_at"],
        "afgerond": rij["completed_at"],
    }


def alle_items(connection: sqlite3.Connection, status: str | None = None) -> dict:
    query = (
        "SELECT * FROM backlog_items "
        "{filter} "
        "ORDER BY CASE status WHEN 'bezig' THEN 0 WHEN 'todo' THEN 1 ELSE 2 END, "
        "CASE priority WHEN 'hoog' THEN 0 WHEN 'normaal' THEN 1 ELSE 2 END, "
        "COALESCE(due_date, '9999-12-31') ASC, created_at DESC"
    )
    if status in STATUSSEN:
        rijen = connection.execute(
            query.format(filter="WHERE status = ?"), (status,)
        ).fetchall()
    else:
        rijen = connection.execute(query.format(filter="")).fetchall()

    tellingen = {sleutel: 0 for sleutel in STATUSSEN}
    for rij in connection.execute(
        "SELECT status, COUNT(*) AS aantal FROM backlog_items GROUP BY status"
    ):
        if rij["status"] in tellingen:
            tellingen[rij["status"]] = int(rij["aantal"])

    return {
        "items": [_rij_naar_item(rij) for rij in rijen],
        "tellingen": tellingen,
        "totaal": sum(tellingen.values()),
        "statussen": [
            {"sleutel": sleutel, "naam": waarde["naam"]}
            for sleutel, waarde in STATUSSEN.items()
        ],
        "prioriteiten": [
            {"sleutel": sleutel, "naam": waarde["naam"]}
            for sleutel, waarde in PRIORITEITEN.items()
        ],
    }


def toevoegen(connection: sqlite3.Connection, gegevens: dict) -> dict:
    titel = str(gegevens.get("titel", "")).strip()
    if not titel:
        raise ValueError("Geef de taak een titel.")
    if len(titel) > MAX_TITEL:
        raise ValueError(f"De titel mag maximaal {MAX_TITEL} tekens lang zijn.")

    omschrijving = str(gegevens.get("omschrijving", "")).strip()[:MAX_OMSCHRIJVING]
    prioriteit = str(gegevens.get("prioriteit", "normaal"))
    if prioriteit not in PRIORITEITEN:
        prioriteit = "normaal"
    status = str(gegevens.get("status", "todo"))
    if status not in STATUSSEN:
        status = "todo"
    deadline = _datum(gegevens.get("deadline"))

    nu = iso(utcnow())
    cursor = connection.execute(
        "INSERT INTO backlog_items "
        "(title, description, status, priority, due_date, created_at, updated_at, completed_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            titel,
            omschrijving,
            status,
            prioriteit,
            deadline,
            nu,
            nu,
            nu if status == "klaar" else None,
        ),
    )
    rij = connection.execute(
        "SELECT * FROM backlog_items WHERE id = ?", (cursor.lastrowid,)
    ).fetchone()
    return _rij_naar_item(rij)


def bijwerken(connection: sqlite3.Connection, item_id: int, gegevens: dict) -> dict:
    bestaand = connection.execute(
        "SELECT * FROM backlog_items WHERE id = ?", (item_id,)
    ).fetchone()
    if bestaand is None:
        raise LookupError("Deze taak bestaat niet (meer).")

    velden: list[str] = []
    waarden: list = []

    if "titel" in gegevens:
        titel = str(gegevens["titel"]).strip()
        if not titel:
            raise ValueError("Geef de taak een titel.")
        velden.append("title = ?")
        waarden.append(titel[:MAX_TITEL])

    if "omschrijving" in gegevens:
        velden.append("description = ?")
        waarden.append(str(gegevens["omschrijving"]).strip()[:MAX_OMSCHRIJVING])

    if "prioriteit" in gegevens:
        prioriteit = str(gegevens["prioriteit"])
        if prioriteit not in PRIORITEITEN:
            raise ValueError("Onbekende prioriteit.")
        velden.append("priority = ?")
        waarden.append(prioriteit)

    if "deadline" in gegevens:
        velden.append("due_date = ?")
        waarden.append(_datum(gegevens["deadline"]))

    if "status" in gegevens:
        status = str(gegevens["status"])
        if status not in STATUSSEN:
            raise ValueError("Onbekende status.")
        velden.append("status = ?")
        waarden.append(status)
        velden.append("completed_at = ?")
        waarden.append(iso(utcnow()) if status == "klaar" else None)

    if not velden:
        return _rij_naar_item(bestaand)

    velden.append("updated_at = ?")
    waarden.append(iso(utcnow()))
    waarden.append(item_id)

    connection.execute(
        f"UPDATE backlog_items SET {', '.join(velden)} WHERE id = ?", waarden
    )
    rij = connection.execute(
        "SELECT * FROM backlog_items WHERE id = ?", (item_id,)
    ).fetchone()
    return _rij_naar_item(rij)


def verwijderen(connection: sqlite3.Connection, item_id: int) -> None:
    cursor = connection.execute("DELETE FROM backlog_items WHERE id = ?", (item_id,))
    if not cursor.rowcount:
        raise LookupError("Deze taak bestaat niet (meer).")


def afgeronde_opruimen(connection: sqlite3.Connection) -> int:
    cursor = connection.execute("DELETE FROM backlog_items WHERE status = 'klaar'")
    return cursor.rowcount or 0


def _datum(waarde) -> str | None:
    """Accepteert een datum als JJJJ-MM-DD, of niets."""
    if waarde in (None, "", "null"):
        return None
    tekst = str(waarde).strip()[:10]
    delen = tekst.split("-")
    if len(delen) != 3:
        raise ValueError("Gebruik een datum in de vorm JJJJ-MM-DD.")
    try:
        jaar, maand, dag = (int(deel) for deel in delen)
    except ValueError:
        raise ValueError("Gebruik een datum in de vorm JJJJ-MM-DD.") from None
    if not (1 <= maand <= 12 and 1 <= dag <= 31 and 2000 <= jaar <= 2999):
        raise ValueError("Deze datum bestaat niet.")
    return f"{jaar:04d}-{maand:02d}-{dag:02d}"
