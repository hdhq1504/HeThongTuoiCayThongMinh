#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

// === CẤU HÌNH WIFI WOKWI ===
const char* SSID = "Wokwi-GUEST";
const char* PASSWORD = "";

// ⚠️ THAY IP MÁY TÍNH CỦA BẠN VÀO ĐÂY
const char *SERVER_IP = "192.168.21.212"; 
const int SERVER_PORT = 5000;

#define DOAM_PIN 34
#define PUMP_PIN 26

// Calibration Wokwi
const int ADC_KHO = 4095;
const int ADC_UOT = 0;

// Ngưỡng tự động
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

  Serial.println("🚀 Wokwi Starting...");
  WiFi.begin(SSID, PASSWORD);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\n✅ WiFi Connected!");
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
    
    String json;
    serializeJson(doc, json);
    
    http.POST(json);
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
      StaticJsonDocument<300> doc;
      deserializeJson(doc, payload);
      
      // Lấy giá trị từ Server
      int svPump = doc["pump_cmd"]; // 0 hoặc 1
      int svAuto = doc["auto"];     // 0 hoặc 1
      
      // Cập nhật chế độ
      autoMode = (svAuto == 1);
      
      // QUAN TRỌNG: Chỉ nghe lệnh Server khi KHÔNG ở chế độ Auto
      if (!autoMode) {
        if (svPump == 1 && !pumpState) {
          pumpState = true;
          digitalWrite(PUMP_PIN, HIGH);
          Serial.println("🎮 Server: BẬT BƠM");
        } else if (svPump == 0 && pumpState) {
          pumpState = false;
          digitalWrite(PUMP_PIN, LOW);
          Serial.println("🎮 Server: TẮT BƠM");
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

    // --- LOGIC TỰ ĐỘNG ---
    if (autoMode) {
      // Nếu đất khô -> Bật
      if (soilPercent < SOIL_LOW && !pumpState) {
        pumpState = true;
        digitalWrite(PUMP_PIN, HIGH);
        Serial.printf("🤖 Auto: BẬT (Đất %.1f%%)\n", soilPercent);
      } 
      // Nếu đất ướt -> Tắt
      else if (soilPercent > SOIL_HIGH && pumpState) {
        pumpState = false;
        digitalWrite(PUMP_PIN, LOW);
        Serial.printf("🤖 Auto: TẮT (Đất %.1f%%)\n", soilPercent);
      }
      // Ở giữa khoảng 45-60%: Giữ nguyên trạng thái cũ
    }

    sendReport();
    getConfig();
    lastUpdate = now;
  }
}