from flask import Flask, render_template, request, jsonify, redirect, url_for
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from ml_models.soil_prediction import SoilMoistureLSTM
from ml_models.weather_integration import WeatherService
from ml_models.anomaly_detection import AnomalyDetector

DB = "tuoi.db"
CHECK_INTERVAL = 5
app = Flask(__name__)

lstm_model = SoilMoistureLSTM(db_path=DB)
weather_service = WeatherService(api_key='6533dab185327987af94afb468d5669d') 
anomaly_detector = AnomalyDetector(db_path=DB)

prediction_cache = {
    'last_update': None,
    'predictions': None,
    'recommendation': None
}

@app.route("/ml")
def ml_dashboard():
    """ML-enhanced dashboard"""
    return render_template("ml_dashboard.html")

@app.route("/api/ml/predict", methods=["GET"])
def ml_predict():
    """Dự đoán độ ẩm 24h tới"""
    try:
        import time
        now = time.time()
        
        # Update cache mỗi giờ
        if (prediction_cache['last_update'] is None or 
            now - prediction_cache['last_update'] > 3600):
            
            print("🔄 Updating ML predictions...")
            predictions = lstm_model.predict_next_24h()
            prediction_cache['predictions'] = predictions
            prediction_cache['last_update'] = now
        else:
            predictions = prediction_cache['predictions']
        
        # Calculate summary
        soil_values = [p['predicted_soil'] for p in predictions]
        summary = {
            'min': round(min(soil_values), 2),
            'max': round(max(soil_values), 2),
            'avg': round(sum(soil_values) / len(soil_values), 2)
        }
        
        return jsonify({
            'status': 'success',
            'predictions': predictions,
            'summary': summary,
            'cached': prediction_cache['last_update'] is not None
        })
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route("/api/ml/recommendation", methods=["GET"])
def ml_recommendation():
    """Gợi ý tưới nước thông minh"""
    try:
        recommendation = lstm_model.get_watering_recommendation()
        recommendation['confidence'] = 0.85
        
        return jsonify({
            'status': 'success',
            'recommendation': recommendation
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route("/api/ml/weather", methods=["GET"])
def ml_weather():
    """Weather data and impact"""
    try:
        location = request.args.get('location', 'Ho Chi Minh City')
        
        current_weather = weather_service.get_current(location)
        forecast = weather_service.get_forecast(location, days=3)
        impact = weather_service.analyze_irrigation_impact(forecast)
        
        return jsonify({
            'status': 'success',
            'current': current_weather,
            'forecast': forecast[:8],  # Next 24h only
            'irrigation_impact': impact
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route("/api/ml/anomaly", methods=["GET"])
def ml_anomaly():
    """Phát hiện bất thường"""
    try:
        anomalies = anomaly_detector.detect()
        
        # Determine system health
        if not anomalies:
            health = 'GOOD'
        elif any(a['severity'] == 'CRITICAL' for a in anomalies):
            health = 'CRITICAL'
        else:
            health = 'WARNING'
        
        return jsonify({
            'status': 'success',
            'anomalies': anomalies,
            'system_health': health
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route("/api/ml/train", methods=["POST"])
def ml_train():
    """Trigger model retraining"""
    try:
        data = request.get_json() or {}
        epochs = data.get('epochs', 50)
        batch_size = data.get('batch_size', 16)
        
        def train_async():
            print("🚀 Starting model training...")
            history = lstm_model.train(epochs=epochs, batch_size=batch_size)
            print("✅ Training completed!")
        
        import threading
        thread = threading.Thread(target=train_async)
        thread.start()
        
        return jsonify({
            'status': 'success',
            'message': 'Training started in background'
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

# ---------- Database helper ----------
def init_db():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute('''
      CREATE TABLE IF NOT EXISTS config(
        id INTEGER PRIMARY KEY,
        auto INTEGER DEFAULT 1,
        use_schedule INTEGER DEFAULT 0,
        start_time TEXT DEFAULT '06:00',
        end_time TEXT DEFAULT '06:10',
        pump_cmd INTEGER DEFAULT 0
      );
    ''')
    cur.execute('''
      CREATE TABLE IF NOT EXISTS logs(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT,
        soil REAL,
        pump INTEGER,
        auto INTEGER,
        wifi_connected INTEGER DEFAULT 0,
        wifi_rssi INTEGER DEFAULT 0
      );
    ''')
    
    # ============================================
    # Auto-migration: Add WiFi columns if they don't exist
    # ============================================
    try:
        cur.execute("PRAGMA table_info(logs)")
        columns = [col[1] for col in cur.fetchall()]
        
        if 'wifi_connected' not in columns:
            print("⚙️ Adding wifi_connected column to logs table...")
            cur.execute("ALTER TABLE logs ADD COLUMN wifi_connected INTEGER DEFAULT 0")
            
        if 'wifi_rssi' not in columns:
            print("⚙️ Adding wifi_rssi column to logs table...")
            cur.execute("ALTER TABLE logs ADD COLUMN wifi_rssi INTEGER DEFAULT 0")
            
        con.commit()
        print("✅ Database schema updated successfully!")
    except Exception as e:
        print(f"⚠️ Migration error (may be safe to ignore): {e}")
    
    # ============================================
    # Add reset_wifi config key
    # ============================================
    try:
        # Create config table with key-value structure if not exists
        cur.execute('''
            CREATE TABLE IF NOT EXISTS config_kv(
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')
        cur.execute("INSERT OR IGNORE INTO config_kv (key, value) VALUES ('reset_wifi', '0')")
        con.commit()
        print("✅ WiFi reset config initialized!")
    except Exception as e:
        print(f"⚠️ Config migration error: {e}")
    
    # ensure one config row
    cur.execute('SELECT COUNT(*) FROM config;')
    if cur.fetchone()[0] == 0:
        cur.execute("INSERT INTO config(auto,use_schedule,start_time,end_time,pump_cmd) VALUES(1,0,'06:00','06:10',0)")
    con.commit()
    con.close()

def get_config():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute('SELECT auto,use_schedule,start_time,end_time,pump_cmd FROM config WHERE id=1')
    r = cur.fetchone()
    con.close()
    return {
        "auto": bool(r[0]),
        "use_schedule": bool(r[1]),
        "start": r[2],
        "end": r[3],
        "pump_cmd": bool(r[4])
    }

def set_config(**kwargs):
    con = sqlite3.connect(DB)
    cur = con.cursor()
    for k,v in kwargs.items():
        if k in ("auto","use_schedule","start_time","end_time","pump_cmd"):
            cur.execute(f"UPDATE config SET {k} = ? WHERE id=1", (v,))
    con.commit()
    con.close()

def append_log(soil, pump, auto, wifi_connected=0, wifi_rssi=0):
    con = sqlite3.connect(DB)
    cur = con.cursor()
    # Use local time instead of UTC for correct time range filtering
    cur.execute("INSERT INTO logs(ts,soil,pump,auto,wifi_connected,wifi_rssi) VALUES(?,?,?,?,?,?)",
                (datetime.now().isoformat(), soil, int(pump), int(auto), int(wifi_connected), int(wifi_rssi)))
    con.commit()
    con.close()

def read_recent_logs(limit=200):
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute("SELECT ts,soil,wifi_connected,wifi_rssi FROM logs ORDER BY id DESC LIMIT ?", (limit,))
    rows = cur.fetchall()
    con.close()
    # return chronological
    return list(reversed(rows))

# ---------- Scheduler ----------
SOIL_LOW = 45.0   # Bật máy bơm khi độ ẩm < 45%
SOIL_HIGH = 60.0  # Tắt máy bơm khi độ ẩm > 60%

def time_to_minutes(tstr):
    try:
        h,m = tstr.split(":")
        return int(h)*60 + int(m)
    except:
        return None

def get_latest_soil():
    """Lấy độ ẩm mới nhất từ logs"""
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute("SELECT soil FROM logs ORDER BY id DESC LIMIT 1")
    row = cur.fetchone()
    con.close()
    return row[0] if row else None

def scheduler_loop():
    """
    Scheduler xử lý 2 chế độ:
    1. Auto by moisture: Tự động dựa trên độ ẩm (ESP32 xử lý, server chỉ monitor)
    2. Auto by schedule: Tự động theo lịch hẹn giờ
    
    Ưu tiên: Schedule > Auto moisture > Manual
    """
    while True:
        cfg = get_config()
        
        # ============================================
        # MODE 1: AUTO BY SCHEDULE (Highest priority)
        # ============================================
        if cfg["use_schedule"]:
            now = datetime.now()
            now_min = now.hour*60 + now.minute
            start = time_to_minutes(cfg["start"])
            end = time_to_minutes(cfg["end"])
            
            if start is not None and end is not None:
                if end < start:  # crosses midnight
                    in_range = (now_min >= start) or (now_min <= end)
                else:
                    in_range = (now_min >= start) and (now_min <= end)
                
                # Set pump based on schedule
                if in_range:
                    if not cfg["pump_cmd"]:
                        print(f"⏰ SCHEDULE: Bật máy bơm ({cfg['start']} - {cfg['end']})")
                        set_config(pump_cmd=1)
                else:
                    if cfg["pump_cmd"]:
                        print(f"⏰ SCHEDULE: Tắt máy bơm (ngoài giờ)")
                        set_config(pump_cmd=0)
        
        # ============================================
        # MODE 2: AUTO BY MOISTURE (Lower priority)
        # ============================================
        # Note: ESP32 tự xử lý logic này trong autoControl()
        # Server chỉ giám sát, không override lệnh từ schedule
        elif cfg["auto"]:
            latest_soil = get_latest_soil()
            if latest_soil is not None:
                # Chỉ cập nhật nếu cần thiết
                if latest_soil < SOIL_LOW and not cfg["pump_cmd"]:
                    print(f"🤖 AUTO MOISTURE: Bật máy bơm (soil {latest_soil:.1f}% < {SOIL_LOW}%)")
                    set_config(pump_cmd=1)
                elif latest_soil > SOIL_HIGH and cfg["pump_cmd"]:
                    print(f"🤖 AUTO MOISTURE: Tắt máy bơm (soil {latest_soil:.1f}% > {SOIL_HIGH}%)")
                    set_config(pump_cmd=0)
        
        # ============================================
        # MODE 3: MANUAL (No auto action)
        # ============================================
        # Nếu cả auto và use_schedule đều tắt, không làm gì
        
        time.sleep(CHECK_INTERVAL)

# ---------- Flask routes ----------
@app.route("/")
def index():
    cfg = get_config()
    logs = read_recent_logs(200)
    return render_template("index.html", config=cfg, logs=logs)

# ESP32 gửi dữ liệu sensor
@app.route("/api/report", methods=["POST"])
def api_report():
    data = request.get_json(force=True)
    soil = float(data.get("soil", 0))
    pump = int(data.get("pump", 0))
    auto = int(data.get("auto", 0))
    wifi_connected = int(data.get("wifi_connected", 0))
    wifi_rssi = int(data.get("wifi_rssi", 0))
    append_log(soil, pump, auto, wifi_connected, wifi_rssi)
    return jsonify({"status":"ok"})

# ESP32 lấy cấu hình (server trả lệnh)
@app.route("/api/config", methods=["GET"])
def api_config():
    cfg = get_config()
    # Check if there's a pending WiFi reset command
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute("SELECT value FROM config_kv WHERE key='reset_wifi'")
    row = cur.fetchone()
    reset_wifi = int(row[0]) if row else 0
    
    # Clear the reset_wifi flag after reading
    if reset_wifi == 1:
        cur.execute("UPDATE config_kv SET value='0' WHERE key='reset_wifi'")
        con.commit()
        print("🔄 WiFi reset command sent to ESP32")
    
    con.close()
    
    # return ints for ease
    return jsonify({
        "pump_cmd": 1 if cfg["pump_cmd"] else 0,
        "auto": 1 if cfg["auto"] else 0,
        "use_schedule": 1 if cfg["use_schedule"] else 0,
        "start": cfg["start"],
        "end": cfg["end"],
        "reset_wifi": reset_wifi
    })

# Web UI gọi để set cấu hình
@app.route("/api/set", methods=["POST"])
def api_set():
    body = request.form or request.get_json() or {}
    
    # Log what's being updated
    print(f"📝 API /api/set called with: {body}")
    
    # Update configuration
    if 'auto' in body:
        auto_val = int(body.get('auto', 0))
        set_config(auto=auto_val)
        print(f"   → Auto moisture: {'ON' if auto_val else 'OFF'}")
        
        # Nếu bật auto, tắt schedule để tránh conflict
        if auto_val:
            set_config(use_schedule=0)
            print(f"   → Auto disable schedule")
    
    if 'use_schedule' in body:
        schedule_val = int(body.get('use_schedule', 0))
        set_config(use_schedule=schedule_val)
        print(f"   → Schedule: {'ON' if schedule_val else 'OFF'}")
        
        # Nếu bật schedule, tắt auto để tránh conflict
        if schedule_val:
            set_config(auto=0)
            print(f"   → Schedule disable auto")
    
    if 'start' in body:
        set_config(start_time=body.get('start'))
        print(f"   → Start time: {body.get('start')}")
        
    if 'end' in body:
        set_config(end_time=body.get('end'))
        print(f"   → End time: {body.get('end')}")
    
    if 'pump_cmd' in body:
        pump_val = int(body.get('pump_cmd'))
        set_config(pump_cmd=pump_val)
        print(f"   → Pump command: {'ON' if pump_val else 'OFF'}")
        
        # Khi điều khiển thủ công, tắt cả auto và schedule
        set_config(auto=0, use_schedule=0)
        print(f"   → Manual control: disable auto & schedule")
    
    # Return JSON for AJAX calls, redirect for form submissions
    if request.is_json:
        return jsonify({"status": "ok", "message": "Configuration updated"})
    else:
        return redirect(url_for('index'))

# API to read recent logs (for chart)
@app.route("/api/logs", methods=["GET"])
def api_logs():
    """
    Get logs with optional time range filter and aggregation
    Query params:
    - range: 'realtime', 'hour', 'day', 'week', 'all'
    
    Realtime: Raw data (last 50 points)
    Hour: Average per minute (60 points)
    Day: Average per hour (24 points)
    Week: Average per day (7 points)
    """
    time_range = request.args.get('range', 'realtime')
    
    con = sqlite3.connect(DB)
    cur = con.cursor()
    
    now = datetime.now()
    
    if time_range == 'realtime':
        # Last 50 records - raw data, no aggregation
        cur.execute("SELECT ts,soil,wifi_connected,wifi_rssi FROM logs ORDER BY id DESC LIMIT 50")
        rows = cur.fetchall()
        rows = list(reversed(rows))  # Oldest to newest
        result = [{"ts":r[0], "soil":r[1], "wifi_connected":r[2], "wifi_rssi":r[3]} for r in rows]
        print(f"📊 Realtime: {len(rows)} raw points")
        
    elif time_range == 'hour':
        # Last 1 hour - average per minute (60 points max)
        one_hour_ago = (now - timedelta(hours=1)).isoformat()
        cur.execute("SELECT ts,soil FROM logs WHERE ts >= ? ORDER BY id ASC", (one_hour_ago,))
        all_rows = cur.fetchall()
        
        # Group by minute and calculate average
        from collections import defaultdict
        minute_data = defaultdict(list)
        
        for ts, soil in all_rows:
            dt = datetime.fromisoformat(ts)
            # Round to minute
            minute_key = dt.replace(second=0, microsecond=0).isoformat()
            minute_data[minute_key].append(soil)
        
        # Calculate averages
        result = []
        for minute_ts in sorted(minute_data.keys()):
            avg_soil = sum(minute_data[minute_ts]) / len(minute_data[minute_ts])
            result.append({"ts": minute_ts, "soil": round(avg_soil, 1), "wifi_connected": 1, "wifi_rssi": -50})
        
        print(f"📊 Hour: {len(all_rows)} records -> {len(result)} minutes (avg per minute)")
        
    elif time_range == 'day':
        # Last 24 hours - average per hour (24 points max)
        one_day_ago = (now - timedelta(days=1)).isoformat()
        cur.execute("SELECT ts,soil FROM logs WHERE ts >= ? ORDER BY id ASC", (one_day_ago,))
        all_rows = cur.fetchall()
        
        # Group by hour and calculate average
        from collections import defaultdict
        hour_data = defaultdict(list)
        
        for ts, soil in all_rows:
            dt = datetime.fromisoformat(ts)
            # Round to hour
            hour_key = dt.replace(minute=0, second=0, microsecond=0).isoformat()
            hour_data[hour_key].append(soil)
        
        # Calculate averages
        result = []
        for hour_ts in sorted(hour_data.keys()):
            avg_soil = sum(hour_data[hour_ts]) / len(hour_data[hour_ts])
            result.append({"ts": hour_ts, "soil": round(avg_soil, 1), "wifi_connected": 1, "wifi_rssi": -50})
        
        print(f"📊 Day: {len(all_rows)} records -> {len(result)} hours (avg per hour)")
        
    elif time_range == 'week':
        # Last 7 days - average per day (7 points max)
        one_week_ago = (now - timedelta(weeks=1)).isoformat()
        cur.execute("SELECT ts,soil FROM logs WHERE ts >= ? ORDER BY id ASC", (one_week_ago,))
        all_rows = cur.fetchall()
        
        # Group by day and calculate average
        from collections import defaultdict
        day_data = defaultdict(list)
        
        for ts, soil in all_rows:
            dt = datetime.fromisoformat(ts)
            # Round to day (midnight)
            day_key = dt.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
            day_data[day_key].append(soil)
        
        # Calculate averages
        result = []
        for day_ts in sorted(day_data.keys()):
            avg_soil = sum(day_data[day_ts]) / len(day_data[day_ts])
            result.append({"ts": day_ts, "soil": round(avg_soil, 1), "wifi_connected": 1, "wifi_rssi": -50})
        
        print(f"📊 Week: {len(all_rows)} records -> {len(result)} days (avg per day)")
        
    else:
        # Default: last 300 records
        cur.execute("SELECT ts,soil,wifi_connected,wifi_rssi FROM logs ORDER BY id DESC LIMIT 300")
        rows = cur.fetchall()
        rows = list(reversed(rows))
        result = [{"ts":r[0], "soil":r[1], "wifi_connected":r[2], "wifi_rssi":r[3]} for r in rows]
    
    con.close()
    
    # Debug: Print summary
    if result:
        print(f"📅 Returning {len(result)} points from {result[0]['ts']} to {result[-1]['ts']}")
    else:
        print(f"⚠️ No data found for time range '{time_range}'")
    
    return jsonify(result)

# API to get system status (for debugging)
@app.route("/api/status", methods=["GET"])
def api_status():
    """Endpoint để kiểm tra trạng thái hệ thống"""
    cfg = get_config()
    latest_soil = get_latest_soil()
    
    # Determine current mode
    mode = "MANUAL"
    if cfg["use_schedule"]:
        mode = "AUTO_SCHEDULE"
    elif cfg["auto"]:
        mode = "AUTO_MOISTURE"
    
    return jsonify({
        "mode": mode,
        "pump": "ON" if cfg["pump_cmd"] else "OFF",
        "auto_moisture": cfg["auto"],
        "use_schedule": cfg["use_schedule"],
        "schedule": {
            "start": cfg["start"],
            "end": cfg["end"]
        },
        "latest_soil": latest_soil,
        "thresholds": {
            "low": SOIL_LOW,
            "high": SOIL_HIGH
        }
    })

# API để reset WiFi của ESP32
@app.route("/api/reset_wifi", methods=["POST"])
def api_reset_wifi():
    """Trigger ESP32 to reset WiFi settings"""
    con = sqlite3.connect(DB)
    cur = con.cursor()
    
    # Ensure reset_wifi key exists
    cur.execute("INSERT OR IGNORE INTO config_kv (key, value) VALUES ('reset_wifi', '0')")
    
    # Set reset_wifi flag
    cur.execute("UPDATE config_kv SET value='1' WHERE key='reset_wifi'")
    con.commit()
    con.close()
    
    print("🔄 WiFi reset flag set. ESP32 will reset on next config poll.")
    
    return jsonify({
        "status": "ok",
        "message": "WiFi reset command sent. ESP32 will restart in AP mode.",
        "next_steps": [
            "1. ESP32 sẽ khởi động lại sau vài giây",
            "2. Kết nối WiFi tên: ESP32_TuoiCay",
            "3. Mật khẩu: 12345678",
            "4. Mở trình duyệt đến: 192.168.4.1",
            "5. Chọn WiFi mới và nhập mật khẩu"
        ]
    })

# ---------- Main ----------
if __name__ == "__main__":
    init_db()
    # start scheduler thread
    t = threading.Thread(target=scheduler_loop, daemon=True)
    t.start()
    app.run(host="0.0.0.0", port=5000, debug=True)
