#!/usr/bin/env python3
"""Start het GoldenKnight dashboard.

Dit bestand verving de eerste versie van ``app.py``, waarin de Flask-app nog
helemaal zelf stond. Alles wat daar gebeurde, gebeurt nu in het project:

* ``POST /api/sensor``  - de XIAO ESP32-C3 levert hier zijn meting af, met
  dezelfde namen als voorheen: temperatuur, luchtvochtigheid en licht. Het
  antwoord is ook hetzelfde gebleven (success / message / data).
* ``GET  /api/sensor``  - de laatst ontvangen meting, nu achter een login.
* ``GET  /``            - de website zelf.

Daar zijn de grafieken, het weer, de backlog, de achtergrond en de beveiliging
bij gekomen. De code daarvan staat in de map ``app/``.

Starten kan met allebei; het maakt niet uit welke je gebruikt:

    python3 app.py
    python3 run.py
"""

from run import main

if __name__ == "__main__":
    main()
