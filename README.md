# GoldenKnight Sensor Dashboard

Een webdashboard voor op de Raspberry Pi 4 (Raspberry Pi OS 64-bit) dat je
sensoren live laat zien, de metingen bewaart en er grafieken van tekent.

Het meten gebeurt op een **Seeed Studio XIAO ESP32-C3**. Die stuurt elke paar
seconden temperatuur, luchtvochtigheid en licht naar de Pi; de Pi meet zelf
niets en zorgt voor het dashboard, de opslag en de grafieken.

```
  XIAO ESP32-C3  -- wifi -->  Raspberry Pi 4
  (DHT22 + LDR)               (dashboard op poort 5000)
```

Het aansluiten en programmeren van de ESP32 staat in [`esp32/README.md`](esp32/README.md),
met een kant-en-klare Arduino-schets.

De oorspronkelijke kaarten met **temperatuur**, **luchtvochtigheid** en
**licht** zijn er nog precies zo, en daar zijn deze onderdelen bij gekomen:

| Onderdeel | Wat het doet |
|---|---|
| 🔒 **Veiligheid** | Inloggen met wachtwoord, een slot na te veel mislukte pogingen, CSRF-bescherming, beveiligingsheaders en een logboek met inlogpogingen |
| 🌦️ **Weersoverzicht** | Het weer van nu, de komende 24 uur en 5 dagen vooruit - gratis via Open-Meteo, zonder API-sleutel |
| 📈 **Grafieken** | Het verloop van elke sensor over 1 uur tot 30 dagen, met tooltips en een tabelweergave |
| 🖼️ **Achtergrond** | Zes ingebouwde achtergronden of je eigen foto, met schuifregelaars voor verduistering en vervaging, plus een licht/donker thema |
| 📋 **Backlog** | Een takenlijst met prioriteit, deadline en status (te doen / mee bezig / klaar) |

Alles draait lokaal op de Pi. De enige verbinding naar buiten is het ophalen
van het weer; zonder internet werkt de rest gewoon door.

---

## Snel starten

```bash
git clone https://github.com/Phoenix232323/Goldemknight.git
cd Goldemknight
bash scripts/installeren.sh
```

Het script maakt een virtuele omgeving, installeert de pakketten en vraagt of
je de sensorbibliotheken en de automatische start wilt instellen.

Daarna open je het dashboard in de browser:

```
http://<ip-van-je-pi>:5000
```

Het IP-adres van je Pi vind je met `hostname -I`.

**Eerste keer inloggen:** gebruikersnaam `admin`, wachtwoord `goldenknight`.
Verander dat wachtwoord meteen bij **Instellingen → Wachtwoord wijzigen**; het
dashboard laat een waarschuwing zien zolang je het standaardwachtwoord gebruikt.

### Handmatig installeren

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
cp .env.example .env          # eventueel aanpassen
./.venv/bin/python run.py
```

---

## De sensoren

### De gewone opzet: de XIAO ESP32-C3

De ESP32-C3 meet en stuurt de waarden naar de Pi met een POST naar
`/api/sensor`. Dat is het enige eindpunt zonder login, want een microcontroller
kan niet inloggen.

Verwachte JSON (Nederlandse namen; Engelse mogen ook):

```json
{ "temperatuur": 21.4, "luchtvochtigheid": 48.0, "licht": 310 }
```

Testen zonder ESP32 kan vanaf elke computer in je netwerk:

```bash
curl -X POST http://<ip-van-je-pi>:5000/api/sensor \
     -H "Content-Type: application/json" \
     -d '{"temperatuur": 21.4, "luchtvochtigheid": 48, "licht": 310}'
```

Bovenin het dashboard zie je meteen of de verbinding staat:

* 🟢 *Live sensordata van de XIAO ESP32-C3*
* 🔴 *Geen bericht van de XIAO ESP32-C3 - laatste bericht 4 minuten geleden*

Na `GK_SENSOR_MAX_AGE` seconden zonder bericht (standaard twee minuten) worden
de waarden leeggemaakt. Zo blijft er nooit een oude meting op het scherm staan
alsof hij van nu is.

### Wie mag metingen sturen?

Standaard mag ieder apparaat op je netwerk dat. Voor thuis is dat prima. Wil je
het dichtzetten, zet dan in `.env`:

```ini
GK_SENSOR_TOKEN=een-lang-zelfverzonnen-wachtwoord
```

en dezelfde waarde in de Arduino-schets bij `SENSOR_TOKEN`. De kaart
*Veiligheid* op het dashboard laat zien of dit aanstaat.

### Andere mogelijkheden

Komt er later toch een sensor rechtstreeks aan de Pi, dan kan dat ook. Zet
`GK_SENSOR_SOURCE=auto` (eerst de ESP32, anders de Pi zelf) of `hardware`.

| Sensor | Aansluiting | Pakket |
|---|---|---|
| DHT11 / DHT22 | GPIO (standaard pin 4, BCM) | `adafruit-circuitpython-dht` |
| BH1750 licht | I2C (adres 0x23) | `smbus2` |
| LDR via MCP3008 | SPI (kanaal 0) | `spidev` |

```bash
sudo apt install -y python3-dev libgpiod2 i2c-tools
./.venv/bin/pip install -r requirements-hardware.txt
sudo raspi-config     # Interface Options -> I2C en SPI aanzetten
```

Met `GK_SENSOR_SOURCE=simulatie` draait het dashboard op realistische nepdata,
handig om alles uit te proberen voordat de hardware er is.

## Instellingen (`.env`)

Alle instellingen staan met uitleg in `.env.example`. De belangrijkste:

```ini
GK_ADMIN_USER=admin              # account bij de eerste start
GK_ADMIN_PASSWORD=goldenknight

GK_SENSOR_SOURCE=esp32           # esp32 | auto | hardware | simulatie | extern
GK_SENSOR_MAX_AGE=120            # zonder bericht zo lang, dan "offline"
#GK_SENSOR_TOKEN=                # zet aan om de POST af te schermen
GK_SAMPLE_INTERVAL=60            # elke minuut een meting bewaren
GK_HISTORY_DAYS=90               # zo lang blijven metingen staan

GK_WEATHER_PLACE=Amsterdam       # naam die op het dashboard komt
GK_WEATHER_LAT=52.3676
GK_WEATHER_LON=4.9041

GK_HTTPS=false                   # op true zodra je https gebruikt
GK_TRUST_PROXY=false             # op true achter nginx of Caddy
```

Je eigen coördinaten zoek je op via <https://open-meteo.com>.

---

## Automatisch starten bij het opstarten

```bash
sudo cp deploy/goldenknight.service /etc/systemd/system/
sudo nano /etc/systemd/system/goldenknight.service   # paden en gebruiker kloppend maken
sudo systemctl daemon-reload
sudo systemctl enable --now goldenknight
```

Handige commando's:

```bash
sudo systemctl status goldenknight     # draait het?
sudo journalctl -u goldenknight -f     # meekijken met het logboek
sudo systemctl restart goldenknight    # herstarten na een wijziging
```

De service draait met **één worker en meerdere threads**. Dat is met opzet:
de achtergrondtaak die metingen wegschrijft hoort maar één keer te draaien.

---

## Over de veiligheid

Het dashboard is gemaakt voor je eigen netwerk, maar houdt er rekening mee dat
zoiets vroeg of laat toch bereikbaar wordt van buitenaf.

* Wachtwoorden worden als **hash** opgeslagen (PBKDF2-SHA256), nooit leesbaar.
* De **sessiecookie** is HttpOnly en SameSite=Lax; met `GK_HTTPS=true` gaat hij
  alleen nog over een versleutelde verbinding.
* Na **5 mislukte pogingen** is inloggen 15 minuten geblokkeerd, per IP-adres.
  Het logboek blijft wél bewaard - dat is juist wat je wilt terugzien.
* Elke wijziging via de API vereist een **CSRF-token**.
* De browser krijgt een strikte **Content-Security-Policy**, `nosniff`,
  `X-Frame-Options: DENY` en een beperkte `Permissions-Policy`.
* **Geüploade achtergronden** worden gecontroleerd op grootte, extensie én op
  de echte inhoud van het bestand, en krijgen een willekeurige naam.
* Een **wachtwoordwijziging logt alle openstaande sessies uit**.
* De kaart *Veiligheid* op het dashboard laat zien wat nog aandacht nodig heeft.

Wil je het dashboard buiten je huisnetwerk bereikbaar maken, doe dat dan via
een VPN (bijvoorbeeld WireGuard) of achter nginx met https - zie
`deploy/nginx-goldenknight.conf`. Zet `GK_HTTPS=true` en `GK_TRUST_PROXY=true`
zodra dat staat.

---

## Beheer vanaf de opdrachtregel

```bash
./.venv/bin/python tools/beheer.py gebruikers               # accounts tonen
./.venv/bin/python tools/beheer.py wachtwoord admin         # wachtwoord wijzigen
./.venv/bin/python tools/beheer.py nieuwe-gebruiker jan     # account toevoegen
./.venv/bin/python tools/beheer.py opschonen 30             # alleen laatste 30 dagen bewaren
```

Wachtwoord vergeten? Gebruik `tools/beheer.py wachtwoord <naam>` op de Pi zelf.

---

## Hoe het in elkaar zit

```
run.py                     start de applicatie
app/
  __init__.py              zet Flask in elkaar, start de meetthread
  config.py                instellingen uit .env
  database.py              SQLite (metingen, backlog, gebruikers, logboek)
  security.py              inloggen, CSRF, slot, headers, veiligheidsoverzicht
  sensors.py               DHT22 / BH1750 / MCP3008 + simulatie
  sampler.py               schrijft elke minuut een meting weg
  history.py               metingen samenvatten voor de grafieken
  weather.py               Open-Meteo, met cache en Nederlandse teksten
  backgrounds.py           achtergronden en uploadcontrole
  backlog.py               takenlijst
  routes/                  pagina's, inloggen, JSON-API
  templates/               HTML
  static/
    css/style.css          vormgeving, licht- en donkerthema
    js/grafiek.js          eigen SVG-grafiek, zonder externe bibliotheken
    js/dashboard.js        bediening van alle onderdelen
esp32/                     Arduino-schets voor de XIAO ESP32-C3 + uitleg
deploy/                    systemd-service en nginx-voorbeeld
scripts/installeren.sh     installatie in één keer
tools/beheer.py            beheer vanaf de opdrachtregel
instance/                  database, uploads en sleutel (niet in git)
```

De grafieken zijn met opzet **zonder Chart.js of D3** gemaakt. Een Pi staat
vaak zonder internet, en dan laadt een grafiek van een CDN niet. `grafiek.js`
tekent alles zelf in SVG en is een paar kilobytes groot.

### API

Alle eindpunten vragen een geldige sessie. Wijzigen vraagt daarnaast de header
`X-CSRF-Token`.

| Methode | Pad | Doel |
|---|---|---|
| POST | `/api/sensor` | **de ESP32 levert hier een meting af** (geen login) |
| GET | `/api/sensor` | de huidige meetwaarden |
| GET | `/api/history?periode=24u` | geschiedenis (`1u`, `6u`, `24u`, `7d`, `30d`) |
| GET | `/api/weer` | weersoverzicht |
| GET | `/api/veiligheid` | controlelijst en inlogpogingen |
| GET/POST/PATCH/DELETE | `/api/backlog` | takenlijst |
| GET/POST | `/api/achtergrond` | achtergrond en thema |
| POST | `/api/wachtwoord` | wachtwoord wijzigen |
| GET | `/gezondheid` | korte statuscheck, zonder inloggen |

`/api/sensor` geeft nog steeds `temperature`, `humidity`, `light` en
`timestamp` terug, dus scripts die dat al gebruikten blijven werken.

---

## Als er iets niet werkt

| Wat je ziet | Wat je kunt doen |
|---|---|
| "Geen bericht van de XIAO ESP32-C3" | De ESP32 komt er niet doorheen. Kijk in de seriële monitor van de Arduino IDE: staat er wifi? klopt het IP-adres van de Pi? Zie [`esp32/README.md`](esp32/README.md). |
| Waarden blijven op `--` staan | De ESP32 stuurt wel iets, maar met andere namen. Het moeten `temperatuur`, `luchtvochtigheid` en `licht` zijn. |
| Grafieken zijn leeg | De metingen beginnen bij de eerste start. Na een uur staat "Laatste uur" vol. |
| Geen weergegevens | De Pi kan `api.open-meteo.com` niet bereiken. Controleer de internetverbinding; de rest van het dashboard werkt gewoon door. |
| Inloggen geblokkeerd | Te veel mislukte pogingen; wacht 15 minuten, of pas `GK_LOGIN_MAX_ATTEMPTS` aan. |
| Poort 5000 is bezet | Zet een andere poort in `.env` met `GK_PORT=5001`. |
| Service start niet | `sudo journalctl -u goldenknight -n 50` laat de reden zien. |

Een schone start (let op: alle metingen en taken zijn dan weg):

```bash
sudo systemctl stop goldenknight
rm -rf instance
sudo systemctl start goldenknight
```
