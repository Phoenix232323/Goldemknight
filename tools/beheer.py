#!/usr/bin/env python3
"""Beheerscript voor het GoldenKnight dashboard.

Voorbeelden:

    python3 tools/beheer.py gebruikers
    python3 tools/beheer.py wachtwoord admin
    python3 tools/beheer.py nieuwe-gebruiker jan
    python3 tools/beheer.py opschonen 30
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app  # noqa: E402
from app.database import (  # noqa: E402
    get_db,
    prune_login_attempts,
    prune_readings,
)
from app.security import (  # noqa: E402
    create_user,
    find_user,
    password_problems,
    set_password,
)


def _vraag_wachtwoord() -> str:
    eerste = getpass.getpass("Nieuw wachtwoord: ")
    tweede = getpass.getpass("Nogmaals: ")
    if eerste != tweede:
        raise SystemExit("De wachtwoorden zijn niet gelijk.")
    problemen = password_problems(eerste)
    if problemen:
        raise SystemExit("Wachtwoord afgekeurd: " + " ".join(problemen))
    return eerste


def main() -> int:
    parser = argparse.ArgumentParser(description="Beheer van het GoldenKnight dashboard")
    sub = parser.add_subparsers(dest="opdracht", required=True)

    sub.add_parser("gebruikers", help="toon alle accounts")

    p_wachtwoord = sub.add_parser("wachtwoord", help="wijzig een wachtwoord")
    p_wachtwoord.add_argument("gebruikersnaam")

    p_nieuw = sub.add_parser("nieuwe-gebruiker", help="maak een nieuw account")
    p_nieuw.add_argument("gebruikersnaam")

    p_opschonen = sub.add_parser("opschonen", help="verwijder oude metingen")
    p_opschonen.add_argument("dagen", type=int, help="bewaar de laatste N dagen")

    argumenten = parser.parse_args()

    app = create_app()
    with app.app_context():
        connection = get_db()

        if argumenten.opdracht == "gebruikers":
            rijen = connection.execute(
                "SELECT username, created_at, last_login_at, must_change_password "
                "FROM users ORDER BY username"
            ).fetchall()
            if not rijen:
                print("Er zijn nog geen accounts.")
            for rij in rijen:
                markering = " (standaardwachtwoord)" if rij["must_change_password"] else ""
                print(
                    f"{rij['username']:<20} aangemaakt {rij['created_at']}  "
                    f"laatste login {rij['last_login_at'] or '-'}{markering}"
                )

        elif argumenten.opdracht == "wachtwoord":
            gebruiker = find_user(connection, argumenten.gebruikersnaam)
            if gebruiker is None:
                raise SystemExit(f"Gebruiker '{argumenten.gebruikersnaam}' bestaat niet.")
            set_password(connection, gebruiker["id"], _vraag_wachtwoord())
            print("Wachtwoord gewijzigd. Openstaande sessies zijn uitgelogd.")

        elif argumenten.opdracht == "nieuwe-gebruiker":
            if find_user(connection, argumenten.gebruikersnaam) is not None:
                raise SystemExit("Die gebruikersnaam bestaat al.")
            create_user(connection, argumenten.gebruikersnaam, _vraag_wachtwoord())
            print(f"Gebruiker '{argumenten.gebruikersnaam}' aangemaakt.")

        elif argumenten.opdracht == "opschonen":
            aantal = prune_readings(connection, argumenten.dagen)
            pogingen = prune_login_attempts(connection, argumenten.dagen)
            print(f"{aantal} oude metingen verwijderd.")
            print(f"{pogingen} oude inlogpogingen verwijderd.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
