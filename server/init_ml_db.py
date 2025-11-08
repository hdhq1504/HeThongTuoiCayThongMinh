import sqlite3

DB = "tuoi.db"

def extend_db():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    
    # 1. Add ML prediction columns to logs table
    try:
        cur.execute("ALTER TABLE logs ADD COLUMN predicted_soil REAL")
        cur.execute("ALTER TABLE logs ADD COLUMN prediction_error REAL")
        cur.execute("ALTER TABLE logs ADD COLUMN weather_temp REAL")
        cur.execute("ALTER TABLE logs ADD COLUMN weather_humidity INTEGER")
        cur.execute("ALTER TABLE logs ADD COLUMN weather_rain REAL")
        print("✅ Added ML columns to logs table")
    except sqlite3.OperationalError as e:
        print(f"ℹ️ Columns may already exist: {e}")
    
    # 2. Create ML predictions table
    cur.execute('''
        CREATE TABLE IF NOT EXISTS ml_predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            prediction_time TEXT NOT NULL,
            predicted_value REAL NOT NULL,
            confidence REAL,
            model_version TEXT
        )
    ''')
    print("✅ Created ml_predictions table")
    
    # 3. Create anomalies table
    cur.execute('''
        CREATE TABLE IF NOT EXISTS anomalies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            type TEXT NOT NULL,
            severity TEXT NOT NULL,
            message TEXT,
            details TEXT,
            resolved INTEGER DEFAULT 0
        )
    ''')
    print("✅ Created anomalies table")
    
    # 4. Create weather cache table
    cur.execute('''
        CREATE TABLE IF NOT EXISTS weather_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            location TEXT,
            data TEXT,
            expires_at TEXT
        )
    ''')
    print("✅ Created weather_cache table")
    
    con.commit()
    con.close()
    print("\n🎉 Database extended successfully!")

if __name__ == "__main__":
    extend_db()