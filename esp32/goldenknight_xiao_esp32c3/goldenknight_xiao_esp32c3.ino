/* ==========================================================================
   GoldenKnight - Seeed Studio XIAO ESP32-C3

   Meet temperatuur, luchtvochtigheid en licht, en stuurt die elke paar
   seconden naar het dashboard op de Raspberry Pi.

   Aansluiten
   ----------
     DHT22 (temperatuur + luchtvochtigheid)
       VCC   -> 3V3
       GND   -> GND
       DATA  -> D2      (zet een weerstand van 10 kOhm tussen DATA en 3V3)

     LDR (licht), als spanningsdeler
       3V3 --- LDR --- A0 --- weerstand 10 kOhm --- GND

   Bibliotheken installeren (Arduino IDE -> Bibliotheekbeheer)
   ----------------------------------------------------------
     - "DHT sensor library"        van Adafruit
     - "Adafruit Unified Sensor"   van Adafruit

   Board installeren
   -----------------
     Bestand -> Voorkeuren -> extra board-URL:
       https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json
     Daarna bij Board kiezen: "XIAO_ESP32C3"
   ========================================================================== */

#include <WiFi.h>
#include <HTTPClient.h>
#include <DHT.h>

// ===================== Hier je eigen gegevens invullen =====================

const char* WIFI_NAAM      = "MijnWifi";          // naam van je wifi-netwerk
const char* WIFI_WACHTWOORD = "MijnWachtwoord";   // wachtwoord van je wifi

// Het IP-adres van de Raspberry Pi. Vraag dit op de Pi op met: hostname -I
const char* PI_ADRES = "192.168.1.42";
const int   PI_POORT = 5000;

// Laat leeg als er geen GK_SENSOR_TOKEN in het .env-bestand van de Pi staat.
const char* SENSOR_TOKEN = "";

// Hoe vaak een meting wordt verstuurd (milliseconden).
const unsigned long INTERVAL_MS = 5000;

// ===================== Pinnen en sensortype ================================

#define DHT_PIN   D2
#define DHT_TYPE  DHT22        // heb je een blauwe DHT11? zet hier DHT11
#define LDR_PIN   A0

// De ESP32-C3 meet analoog in stapjes van 0 tot 4095.
const int LDR_MAX = 4095;

DHT dht(DHT_PIN, DHT_TYPE);

unsigned long vorigeMeting = 0;

// ===========================================================================

void verbindMetWifi() {
  if (WiFi.status() == WL_CONNECTED) {
    return;
  }

  Serial.print("Verbinden met wifi");
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_NAAM, WIFI_WACHTWOORD);

  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < 20000) {
    delay(500);
    Serial.print(".");
  }
  Serial.println();

  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("Verbonden. IP van de ESP32: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("Geen wifi. Klopt de naam en het wachtwoord?");
  }
}

void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.println();
  Serial.println("GoldenKnight sensor - XIAO ESP32-C3");

  dht.begin();
  analogReadResolution(12);
  verbindMetWifi();
}

void loop() {
  if (millis() - vorigeMeting < INTERVAL_MS) {
    return;
  }
  vorigeMeting = millis();

  verbindMetWifi();
  if (WiFi.status() != WL_CONNECTED) {
    return;
  }

  // --- Meten ---------------------------------------------------------------
  float temperatuur = dht.readTemperature();
  float vochtigheid = dht.readHumidity();

  // Een mislukte DHT-meting komt regelmatig voor. Dan slaan we deze ronde over.
  if (isnan(temperatuur) || isnan(vochtigheid)) {
    Serial.println("DHT-meting mislukt, volgende ronde opnieuw.");
    return;
  }

  int ruwLicht = analogRead(LDR_PIN);
  float licht = (float)ruwLicht / LDR_MAX * 100.0;   // omgerekend naar 0-100%

  Serial.printf("Gemeten: %.1f C, %.1f %%, licht %.0f\n",
                temperatuur, vochtigheid, licht);

  // --- Versturen naar de Raspberry Pi --------------------------------------
  char url[80];
  snprintf(url, sizeof(url), "http://%s:%d/api/sensor", PI_ADRES, PI_POORT);

  char body[160];
  snprintf(body, sizeof(body),
           "{\"temperatuur\":%.1f,\"luchtvochtigheid\":%.1f,\"licht\":%.0f}",
           temperatuur, vochtigheid, licht);

  HTTPClient http;
  http.begin(url);
  http.setTimeout(5000);
  http.addHeader("Content-Type", "application/json");
  if (strlen(SENSOR_TOKEN) > 0) {
    http.addHeader("X-Sensor-Token", SENSOR_TOKEN);
  }

  int antwoord = http.POST((uint8_t*)body, strlen(body));

  if (antwoord == 200) {
    Serial.println("Verstuurd naar het dashboard.");
  } else if (antwoord > 0) {
    Serial.printf("Dashboard gaf code %d terug: %s\n",
                  antwoord, http.getString().c_str());
  } else {
    Serial.printf("Versturen mislukt: %s\n",
                  http.errorToString(antwoord).c_str());
  }

  http.end();
}
