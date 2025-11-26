#include <WiFi.h>
#include <HTTPClient.h>
#include <Ticker.h>
#include <ArduinoJson.h>
#include <WiFiManager.h>

// WiFi Manager sẽ tự động xử lý WiFi, không cần hardcode nữa
WiFiManager wm;

// === Địa chỉ server backend (máy local của bạn) ===
const char *SERVER_IP = "192.168.0.218";
const int SERVER_PORT = 5000;

// === Pins ===
#define DOAM_PIN 34
#define PUMP_PIN 26

// === ADC calibration ===
const int ADC_KHO = 4000;
const int ADC_UOT = 2400;

// === Auto threshold ===
const float SOIL_LOW = 45.0;  // Bật máy bơm khi độ ẩm < 45%
const float SOIL_HIGH = 60.0; // Tắt máy bơm khi độ ẩm > 60%

// state
float soilPercent = 0;
bool pumpState = false;
bool autoMode = true;
bool useSchedule = false;
String startTime = "06:00";
String endTime = "06:10";

Ticker sensorTicker;
Ticker pollTicker;

float readSoilPercent()
{
  int raw = analogRead(DOAM_PIN);
  float v = map(raw, ADC_KHO, ADC_UOT, 0, 100);
  v = constrain(v, 0, 100);
  return v;
}

void applyPumpCmd(int cmd)
{
  bool desired = cmd != 0;
  if (desired != pumpState)
  {
    pumpState = desired;
    digitalWrite(PUMP_PIN, pumpState ? HIGH : LOW);
    Serial.printf("Pump set to %s by server\n", pumpState ? "ON" : "OFF");
  }
}

void sendReport()
{
  if (WiFi.status() != WL_CONNECTED)
    return;
  HTTPClient http;
  String url = String("http://") + SERVER_IP + ":" + SERVER_PORT + "/api/report";
  http.begin(url);
  http.addHeader("Content-Type", "application/json");
  StaticJsonDocument<256> doc;
  doc["soil"] = soilPercent;
  doc["pump"] = pumpState ? 1 : 0;
  doc["auto"] = autoMode ? 1 : 0;
  doc["wifi_connected"] = 1;
  doc["wifi_rssi"] = WiFi.RSSI();
  String payload;
  serializeJson(doc, payload);
  int code = http.POST(payload);
  if (code > 0)
  {
    String res = http.getString();
    // we don't need response body now
  }
  else
  {
    Serial.printf("Report failed, err=%d\n", code);
  }
  http.end();
}

void pollConfig()
{
  if (WiFi.status() != WL_CONNECTED)
    return;
  HTTPClient http;
  String url = String("http://") + SERVER_IP + ":" + SERVER_PORT + "/api/config";
  http.begin(url);
  int code = http.GET();
  if (code == HTTP_CODE_OK)
  {
    String body = http.getString();
    StaticJsonDocument<256> doc;
    DeserializationError err = deserializeJson(doc, body);
    if (!err)
    {
      int pump_cmd = doc["pump_cmd"] | 0;
      int auto_v = doc["auto"] | 0;
      int use_s = doc["use_schedule"] | 0;
      int reset_wifi = doc["reset_wifi"] | 0; // Lệnh reset WiFi
      const char *sstart = doc["start"] | "06:00";
      const char *sendt = doc["end"] | "06:10";
      autoMode = auto_v != 0;
      useSchedule = use_s != 0;
      startTime = String(sstart);
      endTime = String(sendt);
      applyPumpCmd(pump_cmd);

      // Reset WiFi nếu có lệnh
      if (reset_wifi == 1)
      {
        Serial.println("🔄 Resetting WiFi settings...");
        wm.resetSettings();
        delay(1000);
        ESP.restart();
      }

      // Log
      Serial.printf("Config: pump_cmd=%d auto=%d use_schedule=%d start=%s end=%s\n",
                    pump_cmd, auto_v, use_s, sstart, sendt);
    }
  }
  else
  {
    Serial.printf("Config GET failed: %d\n", code);
  }
  http.end();
}

void autoControl()
{
  // Chỉ thực hiện auto khi autoMode = true
  if (!autoMode)
    return;

  // Logic tự động: bật khi < 45%, tắt khi > 60%
  if (soilPercent < SOIL_LOW && !pumpState)
  {
    pumpState = true;
    digitalWrite(PUMP_PIN, HIGH);
    Serial.printf("🔵 AUTO: Pump ON (soil %.1f%% < %.1f%%)\n", soilPercent, SOIL_LOW);
  }
  else if (soilPercent > SOIL_HIGH && pumpState)
  {
    pumpState = false;
    digitalWrite(PUMP_PIN, LOW);
    Serial.printf("🔴 AUTO: Pump OFF (soil %.1f%% > %.1f%%)\n", soilPercent, SOIL_HIGH);
  }
}

void readAndReport()
{
  soilPercent = readSoilPercent();
  autoControl(); // Thực hiện điều khiển tự động
  Serial.printf("Soil: %.1f %% | Pump:%s | Auto:%d\n", soilPercent, pumpState ? "ON" : "OFF", autoMode ? 1 : 0);
  sendReport();
}

void setup()
{
  Serial.begin(115200);
  pinMode(PUMP_PIN, OUTPUT);
  digitalWrite(PUMP_PIN, LOW);

  pinMode(DOAM_PIN, INPUT);

  // WiFi Manager - tùy chỉnh giao diện
  // Uncomment dòng dưới nếu muốn reset WiFi đã lưu (để test)
  // wm.resetSettings();

  // Cấu hình timeout cho portal (3 phút)
  wm.setConfigPortalTimeout(180);

  // Tự động kết nối hoặc mở Access Point để cấu hình
  // AP Name: "ESP32_TuoiCay", Password: "12345678"
  Serial.println("🔧 Starting WiFi Manager...");
  Serial.println("📡 If not connected, open WiFi and connect to: ESP32_TuoiCay");
  Serial.println("🔑 Password: 12345678");
  Serial.println("🌐 Then open browser to: 192.168.4.1");

  bool res = wm.autoConnect("ESP32_TuoiCay", "12345678");

  if (!res)
  {
    Serial.println("❌ Failed to connect and timeout");
    delay(3000);
    ESP.restart();
  }
  else
  {
    Serial.println("\n✅ Connected to WiFi!");
    Serial.println("📶 SSID: " + WiFi.SSID());
    Serial.println("🌐 IP: " + WiFi.localIP().toString());
    Serial.println("📡 RSSI: " + String(WiFi.RSSI()) + " dBm");
  }

  Serial.println("✅ Starting ESP32 with optimized timing...");
  sensorTicker.attach(1, readAndReport); // Sensor + Report every 1s
  pollTicker.attach(1, pollConfig);      // Poll config every 1s
}

void loop()
{
  // nothing here, tasks in tickers
  delay(100);
}
