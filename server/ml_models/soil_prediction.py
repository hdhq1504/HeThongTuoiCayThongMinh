import numpy as np
import pandas as pd
from sklearn.preprocessing import MinMaxScaler
from sklearn.model_selection import train_test_split
import tensorflow as tf
from tensorflow import keras
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import LSTM, Dense, Dropout, Bidirectional
from tensorflow.keras.callbacks import EarlyStopping, ModelCheckpoint
import joblib
import sqlite3
from datetime import datetime, timedelta

class SoilMoistureLSTM:
    def __init__(self, db_path='tuoi.db', sequence_length=24):
        """
        Args:
            db_path: Đường dẫn database SQLite
            sequence_length: Số timesteps để dự đoán (default: 24 = 24 giờ)
        """
        self.db_path = db_path
        self.sequence_length = sequence_length
        self.model = None
        self.scaler = MinMaxScaler(feature_range=(0, 1))
        
    def load_data(self, days=30):
        """Load dữ liệu từ database"""
        con = sqlite3.connect(self.db_path)
        
        # Lấy dữ liệu 30 ngày gần nhất
        cutoff_date = (datetime.now() - timedelta(days=days)).isoformat()
        
        query = """
        SELECT 
            ts,
            soil,
            pump,
            auto,
            wifi_rssi
        FROM logs 
        WHERE ts >= ?
        ORDER BY ts ASC
        """
        
        df = pd.read_sql_query(query, con, params=(cutoff_date,))
        con.close()
        
        # Convert timestamp to datetime
        df['ts'] = pd.to_datetime(df['ts'])
        
        # Resample to hourly average (giảm noise)
        df.set_index('ts', inplace=True)
        df_hourly = df.resample('1H').mean().fillna(method='ffill')
        
        print(f"✅ Loaded {len(df_hourly)} hourly records")
        return df_hourly
    
    def create_sequences(self, data, target_col='soil'):
        """Tạo sequences cho LSTM"""
        X, y = [], []
        
        for i in range(len(data) - self.sequence_length):
            X.append(data[i:i + self.sequence_length])
            y.append(data[i + self.sequence_length, data.columns.get_loc(target_col)])
        
        return np.array(X), np.array(y)
    
    def build_model(self, input_shape):
        """Xây dựng LSTM model"""
        model = Sequential([
            # Bidirectional LSTM layer 1
            Bidirectional(LSTM(128, return_sequences=True), 
                         input_shape=input_shape),
            Dropout(0.3),
            
            # LSTM layer 2
            LSTM(64, return_sequences=True),
            Dropout(0.3),
            
            # LSTM layer 3
            LSTM(32),
            Dropout(0.2),
            
            # Dense layers
            Dense(16, activation='relu'),
            Dense(1)  # Output: soil moisture prediction
        ])
        
        model.compile(
            optimizer=keras.optimizers.Adam(learning_rate=0.001),
            loss='mse',
            metrics=['mae']
        )
        
        print("🏗️ Model Architecture:")
        model.summary()
        
        return model
    
    def train(self, epochs=100, batch_size=32, validation_split=0.2):
        """Train model"""
        print("📊 Loading and preprocessing data...")
        
        # Load data
        df = self.load_data(days=60)  # Dùng 60 ngày data
        
        # Feature engineering
        df['hour'] = df.index.hour
        df['day_of_week'] = df.index.dayofweek
        df['is_weekend'] = (df['day_of_week'] >= 5).astype(int)
        
        # Normalize data
        scaled_data = self.scaler.fit_transform(df)
        
        # Create sequences
        X, y = self.create_sequences(pd.DataFrame(scaled_data, columns=df.columns))
        
        print(f"📦 Training data shape: X={X.shape}, y={y.shape}")
        
        # Split train/test
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, shuffle=False
        )
        
        # Build model
        self.model = self.build_model(input_shape=(X.shape[1], X.shape[2]))
        
        # Callbacks
        early_stop = EarlyStopping(
            monitor='val_loss',
            patience=15,
            restore_best_weights=True
        )
        
        checkpoint = ModelCheckpoint(
            'models/lstm_best.h5',
            monitor='val_loss',
            save_best_only=True
        )
        
        # Train
        print("🚀 Training model...")
        history = self.model.fit(
            X_train, y_train,
            epochs=epochs,
            batch_size=batch_size,
            validation_data=(X_test, y_test),
            callbacks=[early_stop, checkpoint],
            verbose=1
        )
        
        # Evaluate
        loss, mae = self.model.evaluate(X_test, y_test, verbose=0)
        print(f"\n✅ Test Loss: {loss:.4f}")
        print(f"✅ Test MAE: {mae:.4f}%")
        
        # Save scaler
        joblib.dump(self.scaler, 'models/scaler.pkl')
        print("💾 Model and scaler saved!")
        
        return history
    
    def predict_next_24h(self):
        """Dự đoán độ ẩm 24 giờ tới"""
        if self.model is None:
            # Load model
            self.model = keras.models.load_model('models/lstm_best.h5')
            self.scaler = joblib.load('models/scaler.pkl')
        
        # Get recent data
        df = self.load_data(days=7)
        
        # Feature engineering
        df['hour'] = df.index.hour
        df['day_of_week'] = df.index.dayofweek
        df['is_weekend'] = (df['day_of_week'] >= 5).astype(int)
        
        # Get last sequence
        scaled_data = self.scaler.transform(df)
        last_sequence = scaled_data[-self.sequence_length:]
        
        predictions = []
        current_sequence = last_sequence.copy()
        
        # Predict next 24 hours
        for hour in range(24):
            # Reshape for prediction
            X_pred = current_sequence.reshape(1, self.sequence_length, -1)
            
            # Predict
            pred_scaled = self.model.predict(X_pred, verbose=0)[0][0]
            
            # Inverse transform to get actual value
            dummy = np.zeros((1, df.shape[1]))
            dummy[0, 0] = pred_scaled  # soil is first column
            pred_actual = self.scaler.inverse_transform(dummy)[0, 0]
            
            predictions.append({
                'hour': hour + 1,
                'timestamp': datetime.now() + timedelta(hours=hour+1),
                'predicted_soil': round(pred_actual, 2)
            })
            
            # Update sequence (sliding window)
            new_row = current_sequence[-1].copy()
            new_row[0] = pred_scaled  # Update soil moisture
            current_sequence = np.vstack([current_sequence[1:], new_row])
        
        print(f"🔮 Predicted next 24h:")
        for p in predictions[:5]:  # Show first 5
            print(f"  Hour {p['hour']}: {p['predicted_soil']:.1f}%")
        
        return predictions
    
    def get_watering_recommendation(self):
        """Gợi ý tưới nước dựa trên dự đoán"""
        predictions = self.predict_next_24h()
        
        # Analyze predictions
        min_moisture = min(p['predicted_soil'] for p in predictions)
        avg_moisture = np.mean([p['predicted_soil'] for p in predictions])
        
        # Decision logic
        if min_moisture < 40:
            recommendation = {
                'action': 'WATER_NOW',
                'reason': f'Độ ẩm sẽ giảm xuống {min_moisture:.1f}% trong 24h tới',
                'suggested_duration': '15 phút',
                'urgency': 'HIGH'
            }
        elif min_moisture < 50 and avg_moisture < 55:
            recommendation = {
                'action': 'WATER_SOON',
                'reason': f'Độ ẩm trung bình {avg_moisture:.1f}%, tối thiểu {min_moisture:.1f}%',
                'suggested_duration': '10 phút',
                'urgency': 'MEDIUM'
            }
        else:
            recommendation = {
                'action': 'NO_WATER',
                'reason': f'Độ ẩm ổn định ở {avg_moisture:.1f}%',
                'suggested_duration': '0 phút',
                'urgency': 'LOW'
            }
        
        print(f"\n💡 Recommendation: {recommendation['action']}")
        print(f"   Reason: {recommendation['reason']}")
        
        return recommendation

# ============================================
# USAGE EXAMPLE
# ============================================

if __name__ == "__main__":
    # Initialize model
    lstm = SoilMoistureLSTM(db_path='tuoi.db', sequence_length=24)
    
    # Train model (chỉ chạy 1 lần hoặc khi cần retrain)
    # history = lstm.train(epochs=50, batch_size=16)
    
    # Make predictions
    predictions = lstm.predict_next_24h()
    
    # Get recommendation
    recommendation = lstm.get_watering_recommendation()