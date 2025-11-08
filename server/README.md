# 🌱 Hệ Thống Tưới Cây Thông Minh - Backend

Backend Flask cho hệ thống tưới cây tự động với ESP32.

## 📋 Tính năng

- ✅ Dashboard web realtime với biểu đồ
- ✅ Hiển thị độ ẩm đất realtime với vòng tròn động
- ✅ Điều khiển máy bơm với toggle switch mượt mà
- ✅ Chế độ tự động dựa trên độ ẩm
- ✅ Hẹn giờ tưới theo lịch
- ✅ Lưu log vào SQLite database
- ✅ API cho ESP32

## 🚀 Cài đặt

```bash
# Cài đặt dependencies
pip install -r requirements.txt

# Chạy server
python app.py
```

Server sẽ chạy tại: http://localhost:5000

## 📡 API Endpoints

### 1. ESP32 gửi dữ liệu cảm biến
```
POST /api/report
Content-Type: application/json

{
  "soil": 45.5,
  "pump": 1,
  "auto": 1
}
```

**Gửi mỗi 1 giây** để có realtime tốt nhất!

### 2. ESP32 lấy lệnh điều khiển
```
GET /api/config

Response:
{
  "pump_cmd": 1,      // 0: TẮT, 1: BẬT
  "auto": 1,          // 0: Manual, 1: Auto
  "use_schedule": 0,  // 0: Không dùng lịch, 1: Dùng lịch
  "start": "06:00",
  "end": "06:10"
}
```

**Poll mỗi 2-3 giây** để kiểm tra lệnh mới.

### 3. Web lấy logs (cho chart)
```
GET /api/logs

Response: [
  {"ts": "2025-10-31T10:30:00", "soil": 45.5},
  ...
]
```

### 4. Web cập nhật cấu hình
```
POST /api/set
Content-Type: application/json

{
  "auto": 1,
  "use_schedule": 1,
  "start": "06:00",
  "end": "18:00",
  "pump_cmd": 1
}
```

## 🔌 Code ESP32 mẫu

```cpp
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

const char* ssid = "YOUR_WIFI";
const char* password = "YOUR_PASSWORD";
const char* serverURL = "http://192.168.1.100:5000";

const int SOIL_PIN = 34;
const int PUMP_PIN = 25;

void setup() {
  Serial.begin(115200);
  pinMode(PUMP_PIN, OUTPUT);
  
  // Kết nối WiFi
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi Connected!");
  Serial.println(WiFi.localIP());
}

void loop() {
  // 1. Đọc cảm biến
  int soilRaw = analogRead(SOIL_PIN);
  float soilPercent = map(soilRaw, 4095, 0, 0, 100); // Đảo ngược nếu cần
  int pumpState = digitalRead(PUMP_PIN);
  
  // 2. Gửi dữ liệu lên server (MỖI 1 GIÂY)
  sendSensorData(soilPercent, pumpState, 1);
  
  // 3. Lấy lệnh từ server (mỗi 2 giây)
  static unsigned long lastConfigCheck = 0;
  if (millis() - lastConfigCheck > 2000) {
    getConfigFromServer();
    lastConfigCheck = millis();
  }
  
  delay(1000); // QUAN TRỌNG: Gửi mỗi 1 giây cho realtime!
}

void sendSensorData(float soil, int pump, int autoMode) {
  if (WiFi.status() == WL_CONNECTED) {
    HTTPClient http;
    http.begin(String(serverURL) + "/api/report");
    http.addHeader("Content-Type", "application/json");
    
    StaticJsonDocument<200> doc;
    doc["soil"] = soil;
    doc["pump"] = pump;
    doc["auto"] = autoMode;
    
    String json;
    serializeJson(doc, json);
    
    int httpCode = http.POST(json);
    if (httpCode > 0) {
      Serial.println("Data sent: " + json);
    }
    http.end();
  }
}

void getConfigFromServer() {
  if (WiFi.status() == WL_CONNECTED) {
    HTTPClient http;
    http.begin(String(serverURL) + "/api/config");
    
    int httpCode = http.GET();
    if (httpCode == 200) {
      String payload = http.getString();
      
      StaticJsonDocument<300> doc;
      deserializeJson(doc, payload);
      
      int pumpCmd = doc["pump_cmd"];
      int autoMode = doc["auto"];
      
      // Điều khiển máy bơm
      digitalWrite(PUMP_PIN, pumpCmd ? HIGH : LOW);
      
      Serial.print("Config: pump=");
      Serial.print(pumpCmd);
      Serial.print(", auto=");
      Serial.println(autoMode);
    }
    http.end();
  }
}
```

## ⚙️ Database Schema

### Table: config
```sql
id              INTEGER PRIMARY KEY
auto            INTEGER (0/1)
use_schedule    INTEGER (0/1)
start_time      TEXT (HH:MM)
end_time        TEXT (HH:MM)
pump_cmd        INTEGER (0/1)
```

### Table: logs
```sql
id      INTEGER PRIMARY KEY AUTOINCREMENT
ts      TEXT (ISO timestamp)
soil    REAL (độ ẩm %)
pump    INTEGER (0/1)
auto    INTEGER (0/1)
```

## 🎨 Features Dashboard

1. **Độ ẩm Realtime** - Vòng tròn SVG với 5 mức:
   - 🏜️ < 20%: Rất khô
   - 🌵 20-40%: Khô
   - 🌿 40-60%: Tối ưu
   - 💧 60-80%: Ẩm
   - 🌊 > 80%: Rất ẩm

2. **Điều khiển máy bơm** - Toggle switch với:
   - Animation quạt xoay khi bật
   - Giọt nước rơi
   - Status banner lớn

3. **Biểu đồ** - Line chart mượt mà, update realtime

4. **Cấu hình** - Form đơn giản với checkboxes và time inputs

## 📊 Timing quan trọng

- **ESP32 → Server**: Gửi sensor data **MỖI 1 GIÂY** (realtime tốt)
- **ESP32 ← Server**: Lấy config **MỖI 2-3 GIÂY** (đủ nhanh)
- **Web ← Server**: Refresh chart **MỖI 1 GIÂY** (realtime smooth)
- **Scheduler check**: **MỖI 5 GIÂY** (background task)

## 🌐 Deploy lên Internet

Để truy cập từ xa:

1. **Ngrok** (đơn giản nhất):
```bash
ngrok http 5000
```

2. **Port Forward** trên router:
   - Forward port 5000 → IP máy tính
   - Truy cập: http://YOUR_PUBLIC_IP:5000

3. **Deploy lên VPS** (production):
   - Upload code lên VPS
   - Dùng Gunicorn + Nginx
   - Domain + SSL certificate

## 📝 Notes

- Database `tuoi.db` tự động tạo khi chạy lần đầu
- Logs được giới hạn 300 records gần nhất (tránh quá tải)
- Scheduler chạy trong background thread
- Thời gian sử dụng UTC (có thể đổi sang local nếu cần)

## 🐛 Troubleshooting

**ESP32 không kết nối được?**
- Check IP máy tính: `ipconfig` (Windows) hoặc `ifconfig` (Linux/Mac)
- Tắt firewall hoặc allow port 5000
- ESP32 và máy tính phải cùng mạng WiFi

**Database lỗi?**
- Xóa file `tuoi.db` và restart server
- Check quyền ghi file trong folder

**Chart không update?**
- Check Console browser (F12) xem có lỗi API không
- Đảm bảo ESP32 đang gửi data mỗi 1 giây

## 📄 License

MIT License - Free to use!
