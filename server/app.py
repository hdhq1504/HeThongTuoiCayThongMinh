import json
import sqlite3
import threading
import time
from datetime import datetime
from flask import Flask, render_template, request, jsonify

# ================= CẤU HÌNH =================
DB = "tuoi.db"
CHECK_INTERVAL = 5

app = Flask(__name__)

# --- TẠM TẮT MQTT ĐỂ CHẠY GIẢ LẬP ỔN ĐỊNH ---
# (Bật lại khi bạn có hardware thật và MQTT Broker)
# app.config['MQTT_BROKER_URL'] = 'localhost'
# ...
# mqtt = Mqtt(app)

# ================= DATABASE & CONFIG =================
def init_db():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    # Tạo bảng config
    cur.execute('''CREATE TABLE IF NOT EXISTS config(
        id INTEGER PRIMARY KEY, 
        auto INTEGER DEFAULT 1, 
        use_schedule INTEGER DEFAULT 0, 
        start_time TEXT DEFAULT "06:00", 
        end_time TEXT DEFAULT "06:10", 
        pump_cmd INTEGER DEFAULT 0
    )''')
    cur.execute('INSERT OR IGNORE INTO config(id, auto) VALUES(1, 1)')
    
    # Tạo bảng logs
    cur.execute('''CREATE TABLE IF NOT EXISTS logs(
        id INTEGER PRIMARY KEY AUTOINCREMENT, 
        ts TEXT, 
        soil REAL, 
        pump INTEGER, 
        auto INTEGER, 
        wifi_connected INTEGER DEFAULT 0, 
        wifi_rssi INTEGER DEFAULT 0
    )''')
    
    # Tạo bảng config phụ (cho reset wifi)
    cur.execute('CREATE TABLE IF NOT EXISTS config_kv(key TEXT PRIMARY KEY, value TEXT)')
    con.commit()
    con.close()

def get_config():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute('SELECT auto,use_schedule,start_time,end_time,pump_cmd FROM config WHERE id=1')
    r = cur.fetchone()
    con.close()
    if r:
        return {"auto": bool(r[0]), "use_schedule": bool(r[1]), "start": r[2], "end": r[3], "pump_cmd": bool(r[4])}
    return {"auto": 1, "pump_cmd": 0} # Default

def set_config(**kwargs):
    con = sqlite3.connect(DB)
    cur = con.cursor()
    for k,v in kwargs.items():
        if k in ("auto","use_schedule","start_time","end_time","pump_cmd"):
            cur.execute(f"UPDATE config SET {k} = ? WHERE id=1", (v,))
    con.commit()
    con.close()
    print(f"⚙️ Config updated: {kwargs}")

def append_log(soil, pump, auto, wifi_connected=1, wifi_rssi=-50):
    try:
        con = sqlite3.connect(DB)
        cur = con.cursor()
        cur.execute("INSERT INTO logs(ts,soil,pump,auto,wifi_connected,wifi_rssi) VALUES(?,?,?,?,?,?)",
                    (datetime.now().isoformat(), soil, int(pump), int(auto), int(wifi_connected), int(wifi_rssi)))
        con.commit()
        con.close()
    except Exception as e:
        print(f"Lỗi ghi log: {e}")

# ================= ROUTES API =================
@app.route("/")
def index():
    cfg = get_config()
    return render_template("index.html", config=cfg)

@app.route("/ml")
def ml_dashboard():
    return render_template("ml_dashboard.html")

# API nhận dữ liệu từ ESP32 (HTTP POST)
@app.route("/api/report", methods=["POST"])
def api_report():
    try:
        data = request.json or request.form
        if not data:
            return jsonify({"status": "error", "message": "No data received"}), 400
            
        print(f"📥 ESP32 Report -> Soil: {data.get('soil')}% | Pump: {data.get('pump')}")
        
        append_log(
            soil=float(data.get("soil", 0)),
            pump=int(data.get("pump", 0)),
            auto=int(data.get("auto", 0)),
            wifi_connected=1,
            wifi_rssi=int(data.get("wifi_rssi", -50))
        )
        return jsonify({"status": "ok"})
    except Exception as e:
        print(f"❌ Error API Report: {e}")
        return jsonify({"status": "error"}), 500

# API gửi cấu hình xuống ESP32
@app.route("/api/config", methods=["GET"])
def api_config():
    cfg = get_config()
    
    # Kiểm tra lệnh reset wifi
    reset_wifi = 0
    try:
        con = sqlite3.connect(DB)
        cur = con.cursor()
        cur.execute("SELECT value FROM config_kv WHERE key='reset_wifi'")
        row = cur.fetchone()
        if row and int(row[0]) == 1:
            reset_wifi = 1
            cur.execute("UPDATE config_kv SET value='0' WHERE key='reset_wifi'")
            con.commit()
            print("🔄 Gửi lệnh Reset WiFi xuống ESP32!")
        con.close()
    except: pass

    return jsonify({
        "pump_cmd": 1 if cfg["pump_cmd"] else 0,
        "auto": 1 if cfg["auto"] else 0,
        "reset_wifi": reset_wifi
    })

@app.route("/api/set", methods=["POST"])
def api_set():
    data = request.json or request.form
    
    if 'pump_cmd' in data:
        # Nếu điều khiển bơm thủ công, tắt chế độ auto
        set_config(pump_cmd=int(data['pump_cmd']), auto=0, use_schedule=0)
    
    if 'auto' in data:
        set_config(auto=int(data['auto']))
        
    return jsonify({"status": "ok"})

@app.route("/api/logs", methods=["GET"])
def api_logs():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute("SELECT ts,soil,wifi_connected,wifi_rssi FROM logs ORDER BY id DESC LIMIT 50")
    rows = list(reversed(cur.fetchall()))
    con.close()
    return jsonify([{"ts":r[0], "soil":r[1], "wifi_connected":r[2], "wifi_rssi":r[3]} for r in rows])

# API Placeholder cho ML (tránh lỗi 404 bên frontend)
@app.route("/api/ml/predict", methods=["GET"])
def ml_predict():
    return jsonify({"status": "success", "predictions": [], "summary": {"min":0,"max":0,"avg":0}})

@app.route("/api/ml/recommendation", methods=["GET"])
def ml_recommendation():
    return jsonify({"status": "success", "recommendation": {"action": "NO_WATER", "reason": "Mô phỏng", "confidence": 1.0, "suggested_duration": "0 min"}})

@app.route("/api/ml/weather", methods=["GET"])
def ml_weather():
    return jsonify({"status": "success", "current": {"temp": 30, "humidity": 70}, "irrigation_impact": {"should_skip": False, "reason": "OK"}})

@app.route("/api/ml/anomaly", methods=["GET"])
def ml_anomaly():
    return jsonify({"status": "success", "anomalies": [], "system_health": "GOOD"})

# ================= SCHEDULER =================
def scheduler_loop():
    while True:
        cfg = get_config()
        if cfg["auto"]:
            con = sqlite3.connect(DB)
            cur = con.cursor()
            cur.execute("SELECT soil FROM logs ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
            con.close()
            
            if row:
                soil = row[0]
                if soil < 45 and not cfg["pump_cmd"]:
                    print("🤖 Auto: Đất khô -> BẬT BƠM")
                    set_config(pump_cmd=1)
                elif soil > 60 and cfg["pump_cmd"]:
                    print("🤖 Auto: Đất ẩm -> TẮT BƠM")
                    set_config(pump_cmd=0)
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    init_db()
    threading.Thread(target=scheduler_loop, daemon=True).start()
    
    # ⚠️ QUAN TRỌNG: host='0.0.0.0' để chấp nhận kết nối từ ngoài (Wokwi)
    print("🚀 Server đang chạy tại http://0.0.0.0:5000")
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)