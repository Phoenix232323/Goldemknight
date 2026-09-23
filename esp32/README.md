# XIAO ESP32-C3 aansluiten op het dashboard

De ESP32-C3 doet het meten, de Raspberry Pi toont en bewaart het. De ESP32
stuurt elke paar seconden een berichtje naar de Pi; de Pi meet zelf niets.

```
  XIAO ESP32-C3  --- wifi -->  Raspberry Pi
  (DHT22 + LDR)                (dashboard op poort 5000)
```

## 1. Bedrading

| Onderdeel | Pin op de XIAO |
|---|---|
| DHT22 VCC | 3V3 |
| DHT22 GND | GND |
| DHT22 DATA | D2 (met 10 kΩ tussen DATA en 3V3) |
| LDR | tussen 3V3 en A0 |
| Weerstand 10 kΩ | tussen A0 en GND |

## 2. Arduino IDE klaarzetten

1. **Bestand → Voorkeuren → extra board-URL's**, plak erin:
   `https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json`
2. **Hulpmiddelen → Board → Board-beheer**: zoek `esp32` en installeer die.
3. Kies als board: **XIAO_ESP32C3**.
4. **Hulpmiddelen → Bibliotheekbeheer**: installeer *DHT sensor library* en
   *Adafruit Unified Sensor* (beide van Adafruit).

## 3. De schets aanpassen

Open `goldenknight_xiao_esp32c3/goldenknight_xiao_esp32c3.ino` en vul bovenin in:

```cpp
const char* WIFI_NAAM       = "MijnWifi";
const char* WIFI_WACHTWOORD = "MijnWachtwoord";
const char* PI_ADRES        = "192.168.1.42";   // hostname -I op de Pi
```

Upload de schets en open de seriële monitor op **115200 baud**. Je hoort te zien:

```
Verbonden. IP van de ESP32: 192.168.1.77
Gemeten: 21.4 C, 48.0 %, licht 31
Verstuurd naar het dashboard.
```

## 4. Controleren

Open het dashboard op de Pi. Bovenin staat dan:

> ● Live sensordata van de XIAO ESP32-C3

Hoort de Pi een tijdje niets, dan verschijnt:

> ● Geen bericht van de XIAO ESP32-C3 - laatste bericht 4 minuten geleden

## Zelf testen zonder ESP32

Je kunt een meting namaken vanaf elke computer in je netwerk:

```bash
curl -X POST http://192.168.1.42:5000/api/sensor \
     -H "Content-Type: application/json" \
     -d '{"temperatuur": 21.4, "luchtvochtigheid": 48, "licht": 310}'
```

## Als het niet werkt

| Wat je ziet | Wat er aan de hand is |
|---|---|
| `DHT-meting mislukt` | Bedrading van de DHT22, of de 10 kΩ weerstand ontbreekt. Een enkele mislukte meting is normaal. |
| `Versturen mislukt: connection refused` | Het dashboard draait niet, of het IP-adres van de Pi klopt niet. |
| `code 401` | Er staat een `GK_SENSOR_TOKEN` in `.env` op de Pi; zet dezelfde waarde in `SENSOR_TOKEN` in de schets. |
| `code 400` | De namen in de JSON kloppen niet. Het moeten `temperatuur`, `luchtvochtigheid` en `licht` zijn. |
| Geen wifi | De ESP32-C3 werkt alleen op 2,4 GHz-wifi, niet op 5 GHz. |
