import numpy as np
import pandas as pd
import sqlite3
from datetime import datetime, timedelta
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
import joblib

class AnomalyDetector:
    """
    Phát hiện các bất thường:
    1. Sensor drift (cảm biến trôi giá trị)
    2. Pump malfunction (máy bơm hoạt động bất thường)
    3. Sudden moisture drop (độ ẩm giảm đột ngột)
    4. System disconnection (mất kết nối)
    5. Water leak (rò rỉ nước)
    """
    
    def __init__(self, db_path='tuoi.db'):
        self.db_path = db_path
        self.model = None
        self.scaler = StandardScaler()
        
        # Thresholds
        self.MOISTURE_DROP_THRESHOLD = 10  # % drop in 1 hour
        self.MOISTURE_SPIKE_THRESHOLD = 15  # % spike in 1 hour
        self.PUMP_MAX_RUNTIME = 30  # minutes continuous
        self.DISCONNECT_THRESHOLD = 300  # seconds
        
    def load_recent_data(self, hours=24):
        """Load dữ liệu gần đây"""
        con = sqlite3.connect(self.db_path)
        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
        
        query = """
        SELECT ts, soil, pump, auto, wifi_connected, wifi_rssi
        FROM logs
        WHERE ts >= ?
        ORDER BY ts ASC
        """
        
        df = pd.read_sql_query(query, con, params=(cutoff,))
        con.close()
        
        if len(df) > 0:
            df['ts'] = pd.to_datetime(df['ts'])
        
        return df
    
    def detect(self):
        """
        Chạy tất cả các detection methods
        
        Returns:
            List of anomalies detected
        """
        anomalies = []
        
        # Load data
        df = self.load_recent_data(hours=24)
        
        if len(df) < 10:
            return [{
                'type': 'insufficient_data',
                'severity': 'INFO',
                'message': 'Không đủ dữ liệu để phân tích (< 10 records)',
                'timestamp': datetime.now().isoformat()
            }]
        
        # Run detection methods
        anomalies.extend(self.detect_sensor_drift(df))
        anomalies.extend(self.detect_moisture_anomalies(df))
        anomalies.extend(self.detect_pump_issues(df))
        anomalies.extend(self.detect_disconnections(df))
        anomalies.extend(self.detect_water_leak(df))
        
        print(f"🔍 Anomaly Detection: Found {len(anomalies)} issues")
        for a in anomalies:
            print(f"   [{a['severity']}] {a['type']}: {a['message']}")
        
        return anomalies
    
    def detect_sensor_drift(self, df):
        """
        Phát hiện sensor drift (cảm biến trôi giá trị)
        
        Method: Check nếu giá trị stuck ở một mức quá lâu
        """
        anomalies = []
        
        if len(df) < 20:
            return anomalies
        
        # Get last 20 readings
        recent = df.tail(20)
        
        # Check if values are too constant (variance too low)
        soil_std = recent['soil'].std()
        
        if soil_std < 0.5:  # Variance < 0.5% trong 20 readings
            anomalies.append({
                'type': 'sensor_drift',
                'severity': 'WARNING',
                'message': f'Cảm biến độ ẩm có thể bị lỗi (variance quá thấp: {soil_std:.2f}%)',
                'timestamp': datetime.now().isoformat(),
                'details': {
                    'std_dev': soil_std,
                    'mean': recent['soil'].mean()
                }
            })
        
        # Check if stuck at exactly 0% or 100%
        if recent['soil'].min() == 0 and recent['soil'].max() == 0:
            anomalies.append({
                'type': 'sensor_failure',
                'severity': 'CRITICAL',
                'message': 'Cảm biến độ ẩm báo 0% liên tục - có thể bị đứt dây',
                'timestamp': datetime.now().isoformat()
            })
        
        if recent['soil'].min() == 100 and recent['soil'].max() == 100:
            anomalies.append({
                'type': 'sensor_failure',
                'severity': 'CRITICAL',
                'message': 'Cảm biến độ ẩm báo 100% liên tục - có thể bị ngập nước',
                'timestamp': datetime.now().isoformat()
            })
        
        return anomalies
    
    def detect_moisture_anomalies(self, df):
        """
        Phát hiện biến động độ ẩm bất thường
        """
        anomalies = []
        
        if len(df) < 2:
            return anomalies
        
        # Calculate hourly changes
        df_sorted = df.sort_values('ts')
        df_sorted['soil_diff'] = df_sorted['soil'].diff()
        
        # Sudden drop
        max_drop = df_sorted['soil_diff'].min()
        if max_drop < -self.MOISTURE_DROP_THRESHOLD:
            idx = df_sorted['soil_diff'].idxmin()
            anomalies.append({
                'type': 'sudden_moisture_drop',
                'severity': 'WARNING',
                'message': f'Độ ẩm giảm đột ngột {abs(max_drop):.1f}% - kiểm tra rò rỉ',
                'timestamp': df_sorted.loc[idx, 'ts'].isoformat(),
                'details': {
                    'drop_amount': abs(max_drop),
                    'from': df_sorted.loc[idx-1, 'soil'] if idx > 0 else None,
                    'to': df_sorted.loc[idx, 'soil']
                }
            })
        
        # Sudden spike (không tự nhiên)
        max_spike = df_sorted['soil_diff'].max()
        if max_spike > self.MOISTURE_SPIKE_THRESHOLD:
            idx = df_sorted['soil_diff'].idxmax()
            
            # Check if pump was on (spike is expected)
            pump_was_on = df_sorted.loc[idx, 'pump'] == 1
            
            if not pump_was_on:
                anomalies.append({
                    'type': 'unexplained_moisture_spike',
                    'severity': 'WARNING',
                    'message': f'Độ ẩm tăng đột ngột {max_spike:.1f}% khi máy bơm tắt',
                    'timestamp': df_sorted.loc[idx, 'ts'].isoformat(),
                    'details': {
                        'spike_amount': max_spike,
                        'pump_state': 'OFF'
                    }
                })
        
        return anomalies
    
    def detect_pump_issues(self, df):
        """
        Phát hiện vấn đề máy bơm
        """
        anomalies = []
        
        # Find continuous pump ON periods
        df_sorted = df.sort_values('ts')
        df_sorted['pump_change'] = df_sorted['pump'].diff().fillna(0)
        
        # Get ON periods
        on_starts = df_sorted[df_sorted['pump_change'] == 1].index
        on_ends = df_sorted[df_sorted['pump_change'] == -1].index
        
        for start_idx in on_starts:
            # Find corresponding end
            end_candidates = on_ends[on_ends > start_idx]
            
            if len(end_candidates) == 0:
                # Pump still ON
                duration = (datetime.now() - df_sorted.loc[start_idx, 'ts']).total_seconds() / 60
            else:
                end_idx = end_candidates[0]
                duration = (df_sorted.loc[end_idx, 'ts'] - df_sorted.loc[start_idx, 'ts']).total_seconds() / 60
            
            # Check if duration exceeds threshold
            if duration > self.PUMP_MAX_RUNTIME:
                anomalies.append({
                    'type': 'pump_long_runtime',
                    'severity': 'WARNING',
                    'message': f'Máy bơm chạy liên tục {duration:.1f} phút (vượt {self.PUMP_MAX_RUNTIME} phút)',
                    'timestamp': df_sorted.loc[start_idx, 'ts'].isoformat(),
                    'details': {
                        'duration_minutes': duration
                    }
                })
        
        # Check pump effectiveness
        # If pump ON but moisture not increasing → pump issue or leak
        pump_on_periods = df_sorted[df_sorted['pump'] == 1]
        if len(pump_on_periods) > 5:
            soil_change = pump_on_periods['soil'].iloc[-1] - pump_on_periods['soil'].iloc[0]
            
            if soil_change < 2:  # Độ ẩm tăng < 2% sau bơm
                anomalies.append({
                    'type': 'pump_ineffective',
                    'severity': 'CRITICAL',
                    'message': 'Máy bơm hoạt động nhưng độ ẩm không tăng - kiểm tra máy bơm/đường ống',
                    'timestamp': pump_on_periods.iloc[-1]['ts'].isoformat(),
                    'details': {
                        'soil_change': soil_change
                    }
                })
        
        return anomalies
    
    def detect_disconnections(self, df):
        """
        Phát hiện mất kết nối
        """
        anomalies = []
        
        # Check last update time
        if len(df) > 0:
            last_update = df['ts'].max()
            time_since_update = (datetime.now() - last_update).total_seconds()
            
            if time_since_update > self.DISCONNECT_THRESHOLD:
                anomalies.append({
                    'type': 'system_disconnected',
                    'severity': 'CRITICAL',
                    'message': f'Mất kết nối với ESP32 ({time_since_update/60:.1f} phút)',
                    'timestamp': datetime.now().isoformat(),
                    'details': {
                        'last_update': last_update.isoformat(),
                        'seconds_ago': time_since_update
                    }
                })
        
        # Check WiFi signal quality
        recent = df.tail(10)
        if len(recent) > 0:
            avg_rssi = recent['wifi_rssi'].mean()
            
            if avg_rssi < -80:  # Very weak signal
                anomalies.append({
                    'type': 'weak_wifi_signal',
                    'severity': 'WARNING',
                    'message': f'Tín hiệu WiFi yếu (RSSI: {avg_rssi:.0f} dBm)',
                    'timestamp': datetime.now().isoformat(),
                    'details': {
                        'rssi': avg_rssi
                    }
                })
        
        return anomalies
    
    def detect_water_leak(self, df):
        """
        Phát hiện rò rỉ nước
        
        Logic: Độ ẩm giảm nhanh bất thường khi máy bơm tắt
        """
        anomalies = []
        
        if len(df) < 10:
            return anomalies
        
        # Get periods when pump is OFF
        df_sorted = df.sort_values('ts')
        pump_off = df_sorted[df_sorted['pump'] == 0].copy()
        
        if len(pump_off) > 5:
            # Calculate rate of moisture decrease
            pump_off['time_diff'] = pump_off['ts'].diff().dt.total_seconds() / 3600  # hours
            pump_off['moisture_rate'] = pump_off['soil'].diff() / pump_off['time_diff']
            
            # Normal evaporation: -1 to -3% per hour
            # Leak: > -5% per hour
            abnormal_rates = pump_off[pump_off['moisture_rate'] < -5]
            
            if len(abnormal_rates) > 0:
                worst = abnormal_rates['moisture_rate'].min()
                anomalies.append({
                    'type': 'possible_water_leak',
                    'severity': 'CRITICAL',
                    'message': f'Độ ẩm giảm quá nhanh ({worst:.1f}%/h) khi máy bơm tắt - nghi rò rỉ',
                    'timestamp': datetime.now().isoformat(),
                    'details': {
                        'rate_per_hour': worst
                    }
                })
        
        return anomalies
    
    def train_isolation_forest(self):
        """
        Train Isolation Forest model cho general anomaly detection
        (Advanced - có thể bỏ qua nếu chưa đủ data)
        """
        df = self.load_recent_data(hours=24*30)  # 30 days
        
        if len(df) < 100:
            print("⚠️ Không đủ dữ liệu để train Isolation Forest")
            return
        
        # Feature engineering
        df['hour'] = df['ts'].dt.hour
        df['soil_rolling_mean'] = df['soil'].rolling(window=5).mean()
        df['soil_rolling_std'] = df['soil'].rolling(window=5).std()
        
        features = ['soil', 'pump', 'wifi_rssi', 'hour', 
                   'soil_rolling_mean', 'soil_rolling_std']
        
        X = df[features].dropna()
        
        # Train model
        self.model = IsolationForest(
            contamination=0.05,  # Expect 5% anomalies
            random_state=42
        )
        
        X_scaled = self.scaler.fit_transform(X)
        self.model.fit(X_scaled)
        
        # Save model
        joblib.dump(self.model, 'models/anomaly_detector.pkl')
        joblib.dump(self.scaler, 'models/anomaly_scaler.pkl')
        
        print("✅ Isolation Forest model trained and saved!")


# ============================================
# USAGE EXAMPLE
# ============================================

if __name__ == "__main__":
    detector = AnomalyDetector(db_path='tuoi.db')
    
    # Detect anomalies
    anomalies = detector.detect()
    
    # Print results
    print(f"\n📊 Detection Summary: {len(anomalies)} anomalies found")
    
    for anomaly in anomalies:
        severity_icon = {
            'INFO': 'ℹ️',
            'WARNING': '⚠️',
            'CRITICAL': '🚨'
        }.get(anomaly['severity'], '❓')
        
        print(f"\n{severity_icon} {anomaly['type'].upper()}")
        print(f"   Message: {anomaly['message']}")
        print(f"   Time: {anomaly['timestamp']}")
        if 'details' in anomaly:
            print(f"   Details: {anomaly['details']}")