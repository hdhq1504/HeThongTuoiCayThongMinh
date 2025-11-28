import json
import sqlite3
import time
import requests
import threading
from datetime import datetime
from flask import Flask, render_template, request, jsonify
from flask_mqtt import Mqtt

# ================= CẤU HÌNH HỆ THỐNG =================
DB = "tuoi.db"
CHECK_INTERVAL = 5

# --- CẤU HÌNH TELEGRAM (Điền Token của bạn) ---
TELEGRAM_TOKEN = "8308724139:AAEfo9b9MnrhExCvx1cjPJ-GuWgHSMyyk3M" 
TELEGRAM_CHAT_ID = "5588486962"

app = Flask(__name__)

# --- CẤU HÌNH MQTT ---
app.config['MQTT_BROKER_URL'] = 'broker.hivemq.com'
app.config['MQTT_BROKER_PORT'] = 1883
app.config['MQTT_USERNAME'] = ''
app.config['MQTT_PASSWORD'] = ''
app.config['MQTT_KEEPALIVE'] = 5
app.config['MQTT_TLS_ENABLED'] = False

mqtt = Mqtt(app)

# ================= DATABASE =================
def init_db():
    try:
        con = sqlite3.connect(DB)
        cur = con.cursor()
        # Bảng cấu hình
        cur.execute('''CREATE TABLE IF NOT EXISTS config(
            id INTEGER PRIMARY KEY, 
            auto INTEGER DEFAULT 1, 
            use_schedule INTEGER DEFAULT 0,
            start_time TEXT DEFAULT '06:00',
            end_time TEXT DEFAULT '06:10',
            pump_cmd INTEGER DEFAULT 0
        )''')
        cur.execute('INSERT OR IGNORE INTO config(id, auto) VALUES(1, 1)')
        
        # Bảng nhật ký
        cur.execute('''CREATE TABLE IF NOT EXISTS logs(
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            ts TEXT, soil REAL, pump INTEGER, auto INTEGER, 
            wifi_connected INTEGER DEFAULT 0, wifi_rssi INTEGER DEFAULT 0
        )''')
        con.commit()
        con.close()
        print("✅ Database initialized successfully!")
    except Exception as e:
        print(f"❌ DB Init Error: {e}")

def append_log(soil, pump, auto, wifi_connected=1, wifi_rssi=-50):
    try:
        con = sqlite3.connect(DB)
        con.execute("INSERT INTO logs(ts,soil,pump,auto,wifi_connected,wifi_rssi) VALUES(?,?,?,?,?,?)",
                    (datetime.now().isoformat(), soil, int(pump), int(auto), int(wifi_connected), int(wifi_rssi)))
        con.commit()
        con.close()
    except: pass

def get_config():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute('SELECT auto, pump_cmd, use_schedule, start_time, end_time FROM config WHERE id=1')
    row = cur.fetchone()
    con.close()
    if row:
        return {
            "auto": 1 if row[0] else 0, 
            "pump_cmd": 1 if row[1] else 0,
            "use_schedule": 1 if row[2] else 0,
            "start": row[3],
            "end": row[4]
        }
    return {"auto": 1, "pump_cmd": 0, "use_schedule": 0, "start": "06:00", "end": "06:10"}

def set_config_db(**kwargs):
    con = sqlite3.connect(DB)
    for k, v in kwargs.items():
        if k in ("auto", "pump_cmd", "use_schedule", "start_time", "end_time"):
            con.execute(f"UPDATE config SET {k} = ? WHERE id=1", (v,))
    con.commit()
    con.close()

# ================= TELEGRAM BOT =================
def send_telegram(message):
    if "YOUR_BOT_TOKEN" in TELEGRAM_TOKEN: return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
        # Chạy trong thread riêng để không làm chậm server
        threading.Thread(target=lambda: requests.post(url, json=data)).start()
    except Exception as e:
        print(f"⚠️ Telegram Error: {e}")

# ================= MQTT HANDLERS =================
@mqtt.on_connect()
def handle_connect(client, userdata, flags, rc):
    if rc == 0:
        print("✅ Connected to MQTT Broker")
        mqtt.subscribe('tuoicay/report')

@mqtt.on_message()
def handle_mqtt_message(client, userdata, message):
    if message.topic == 'tuoicay/report':
        try:
            data = json.loads(message.payload.decode())
            append_log(data.get('soil', 0), data.get('pump', 0), data.get('auto', 1))
        except: pass

# ================= SCHEDULER (ĐÃ CẬP NHẬT TELEGRAM) =================
def scheduler_loop():
    """Vòng lặp kiểm tra tự động (Auto Moisture & Schedule)"""
    while True:
        try:
            cfg = get_config()
            con = sqlite3.connect(DB)
            cur = con.cursor()
            cur.execute("SELECT soil FROM logs ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
            con.close()
            
            current_soil = row[0] if row else 0

            # 1. Logic Hẹn Giờ (Ưu tiên cao nhất)
            if cfg['use_schedule'] == 1:
                now = datetime.now().strftime("%H:%M")
                if cfg['start'] <= now <= cfg['end']:
                    if cfg['pump_cmd'] == 0:
                        print(f"⏰ Đến giờ hẹn ({now}): BẬT BƠM")
                        set_config_db(pump_cmd=1)
                        send_telegram(f"⏰ *LỊCH HẸN*: Đã đến giờ tưới ({now}) -> **BẬT BƠM**")
                else:
                    if cfg['pump_cmd'] == 1 and cfg['auto'] == 0: # Chỉ tắt nếu không phải auto moisture
                        print(f"⏰ Hết giờ hẹn ({now}): TẮT BƠM")
                        set_config_db(pump_cmd=0)
                        send_telegram(f"⏰ *LỊCH HẸN*: Đã hết giờ tưới ({now}) -> **TẮT BƠM**")

            # 2. Logic Tự Động Theo Độ Ẩm (Khi không dùng lịch)
            elif cfg['auto'] == 1:
                if current_soil < 45 and cfg['pump_cmd'] == 0:
                    print("🤖 Auto: Đất khô -> BẬT BƠM")
                    set_config_db(pump_cmd=1)
                    send_telegram(f"🤖 *AUTO*: Đất khô ({current_soil}%) -> **BẬT BƠM**")
                
                elif current_soil > 60 and cfg['pump_cmd'] == 1:
                    print("🤖 Auto: Đất ẩm -> TẮT BƠM")
                    set_config_db(pump_cmd=0)
                    send_telegram(f"🤖 *AUTO*: Đất đủ ẩm ({current_soil}%) -> **TẮT BƠM**")

        except Exception as e:
            print(f"Scheduler Error: {e}")
        
        time.sleep(CHECK_INTERVAL)

# ================= API =================
@app.route("/")
def index():
    return render_template("index.html", config=get_config())

@app.route("/ml")
def ml_dashboard():
    return render_template("ml_dashboard.html")

@app.route("/api/report", methods=["POST"])
def api_report():
    try:
        data = request.json or request.form
        soil = float(data.get("soil", 0))
        pump = int(data.get("pump", 0))
        auto = int(data.get("auto", 0))
        
        append_log(soil, pump, auto, 1, int(data.get("wifi_rssi", -50)))
        mqtt.publish('tuoicay/report', json.dumps(data))
        print(f"📥 Wokwi: Soil {soil}% | Pump {pump}")
        
        # Cảnh báo khẩn cấp
        if soil < 20 and pump == 0 and auto == 1:
             send_telegram(f"🚨 *CẢNH BÁO*: Đất quá khô ({soil}%) mà bơm chưa bật! Kiểm tra ngay.")

        return jsonify({"status": "ok"})
    except: return jsonify({"status": "error"}), 500

@app.route("/api/config", methods=["GET"])
def api_config():
    return jsonify(get_config())

@app.route("/api/set", methods=["POST"])
def api_set():
    data = request.json or request.form
    mqtt_msg = {}
    
    if 'pump_cmd' in data:
        val = int(data['pump_cmd'])
        set_config_db(pump_cmd=val, auto=0, use_schedule=0)
        mqtt_msg['pump'] = val
        send_telegram(f"👨‍💻 *THỦ CÔNG*: Bạn đã **{'BẬT' if val else 'TẮT'}** bơm.")
        
    if 'auto' in data:
        val = int(data['auto'])
        set_config_db(auto=val, use_schedule=0)
        mqtt_msg['auto'] = val
        send_telegram(f"⚙️ Chế độ: **{'TỰ ĐỘNG (Độ ẩm)' if val else 'THỦ CÔNG'}**")

    if 'use_schedule' in data:
        val = int(data['use_schedule'])
        set_config_db(use_schedule=val, auto=0)
        send_telegram(f"📅 Chế độ: **{'HẸN GIỜ' if val else 'THỦ CÔNG'}**")
        
    if mqtt_msg:
        mqtt.publish('tuoicay/command', json.dumps(mqtt_msg))

    return jsonify({"status": "ok"})

@app.route("/api/logs", methods=["GET"])
def api_logs():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute("SELECT ts,soil,wifi_connected,wifi_rssi FROM logs ORDER BY id DESC LIMIT 50")
    rows = list(reversed(cur.fetchall()))
    con.close()
    return jsonify([{"ts":r[0], "soil":r[1], "wifi_connected":1, "wifi_rssi":-50} for r in rows])

# Placeholders
@app.route("/api/ml/predict", methods=["GET"])
def ml_predict(): return jsonify({"status": "success", "predictions": [], "summary": {"min":0,"max":0,"avg":0}})
@app.route("/api/ml/recommendation", methods=["GET"])
def ml_recommendation(): return jsonify({"status": "success", "recommendation": {"action": "NO_WATER", "reason": "Sim Mode", "confidence": 1.0}})
@app.route("/api/ml/weather", methods=["GET"])
def ml_weather(): return jsonify({"status": "success", "current": {"temp": 30, "humidity": 70}, "irrigation_impact": {"should_skip": False, "reason": "OK"}})
@app.route("/api/ml/anomaly", methods=["GET"])
def ml_anomaly(): return jsonify({"status": "success", "anomalies": [], "system_health": "GOOD"})

if __name__ == "__main__":
    init_db()
    threading.Thread(target=scheduler_loop, daemon=True).start()
    print("🚀 Server & Telegram Bot đang chạy...")
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)