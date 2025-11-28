#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

// === CẤU HÌNH WIFI WOKWI ===
const char* SSID = "Wokwi-GUEST";
const char* PASSWORD = "";

// === CẤU HÌNH SERVER ===
const char *SERVER_IP = "192.168.21.212"; 
const int SERVER_PORT = 5000;

#define DOAM_PIN 34
#define PUMP_PIN 26

// Calibration Wokwi
const int ADC_KHO = 4095;
const int ADC_UOT = 0;

// Ngưỡng tự động (chạy song song backup cho server)
const float SOIL_LOW = 45.0;
const float SOIL_HIGH = 60.0;

float soilPercent = 0;
bool pumpState = false;
bool autoMode = true;
unsigned long lastUpdate = 0;

void setup() {
  Serial.begin(115200);
  pinMode(PUMP_PIN, OUTPUT);
  pinMode(DOAM_PIN, INPUT);

  Serial.println("🚀 Wokwi ESP32 Starting...");
  WiFi.begin(SSID, PASSWORD);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\n✅ WiFi Connected!");
  Serial.print("📡 IP: ");
  Serial.println(WiFi.localIP());
}

void sendReport() {
  if (WiFi.status() == WL_CONNECTED) {
    HTTPClient http;
    String url = String("http://") + SERVER_IP + ":" + SERVER_PORT + "/api/report";
    
    http.begin(url);
    http.addHeader("Content-Type", "application/json");
    
    StaticJsonDocument<200> doc;
    doc["soil"] = soilPercent;
    doc["pump"] = pumpState ? 1 : 0;
    doc["auto"] = autoMode ? 1 : 0;
    doc["wifi_rssi"] = WiFi.RSSI();
    
    String json;
    serializeJson(doc, json);
    
    int httpCode = http.POST(json);
    if (httpCode > 0) {
      Serial.printf("📤 Report OK: %.1f%% | Pump: %d\n", soilPercent, pumpState);
    } else {
      Serial.printf("❌ Report Fail: %s\n", http.errorToString(httpCode).c_str());
    }
    http.end();
  }
}

void getConfig() {
  if (WiFi.status() == WL_CONNECTED) {
    HTTPClient http;
    String url = String("http://") + SERVER_IP + ":" + SERVER_PORT + "/api/config";
    
    http.begin(url);
    int httpCode = http.GET();
    
    if (httpCode == 200) {
      String payload = http.getString();
      StaticJsonDocument<200> doc;
      deserializeJson(doc, payload);
      
      int svPump = doc["pump_cmd"];
      int svAuto = doc["auto"];
      
      // Đồng bộ trạng thái từ Server
      autoMode = (svAuto == 1);
      
      // Nếu Server đang Manual (auto=0), ưu tiên lệnh bơm từ Server
      if (!autoMode) {
        if (svPump == 1 && !pumpState) {
          pumpState = true;
          digitalWrite(PUMP_PIN, HIGH);
          Serial.println("🎮 Server: FORCE PUMP ON");
        } else if (svPump == 0 && pumpState) {
          pumpState = false;
          digitalWrite(PUMP_PIN, LOW);
          Serial.println("🎮 Server: FORCE PUMP OFF");
        }
      }
    }
    http.end();
  }
}

void loop() {
  unsigned long now = millis();
  
  if (now - lastUpdate > 1000) { // Mỗi 1 giây
    int raw = analogRead(DOAM_PIN);
    soilPercent = map(raw, ADC_KHO, ADC_UOT, 0, 100);
    soilPercent = constrain(soilPercent, 0, 100);

    // Logic Tự động tại ESP32 (Phản hồi nhanh)
    if (autoMode) {
      if (soilPercent < SOIL_LOW && !pumpState) {
        pumpState = true;
        digitalWrite(PUMP_PIN, HIGH);
      } else if (soilPercent > SOIL_HIGH && pumpState) {
        pumpState = false;
        digitalWrite(PUMP_PIN, LOW);
      }
    }

    sendReport();
    getConfig();
    lastUpdate = now;
  }
}