import requests
from datetime import datetime, timedelta
import json

class WeatherService:
    """
    Tích hợp OpenWeatherMap API
    Free tier: 1000 calls/day
    """
    
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = "https://api.openweathermap.org/data/2.5"
        
    def get_current(self, location="Ho Chi Minh City"):
        """
        Lấy thời tiết hiện tại
        
        Returns:
            {
                "temp": 28.5,
                "humidity": 75,
                "description": "scattered clouds",
                "rain": 0,
                "wind_speed": 3.5
            }
        """
        try:
            url = f"{self.base_url}/weather"
            params = {
                'q': location,
                'appid': self.api_key,
                'units': 'metric',
                'lang': 'vi'
            }
            
            response = requests.get(url, params=params, timeout=10)
            data = response.json()
            
            if response.status_code != 200:
                raise Exception(f"API Error: {data.get('message', 'Unknown error')}")
            
            # Parse response
            weather = {
                'temp': data['main']['temp'],
                'humidity': data['main']['humidity'],
                'description': data['weather'][0]['description'],
                'rain': data.get('rain', {}).get('1h', 0),  # Rain volume last 1h
                'wind_speed': data['wind']['speed'],
                'clouds': data['clouds']['all'],
                'timestamp': datetime.now().isoformat()
            }
            
            print(f"🌤️ Current weather in {location}:")
            print(f"   Temp: {weather['temp']}°C")
            print(f"   Humidity: {weather['humidity']}%")
            print(f"   Rain: {weather['rain']}mm")
            
            return weather
            
        except Exception as e:
            print(f"❌ Weather API Error: {e}")
            return None
    
    def get_forecast(self, location="Ho Chi Minh City", days=3):
        """
        Lấy dự báo thời tiết
        
        Args:
            location: Tên thành phố
            days: Số ngày dự báo (1-5)
        
        Returns:
            [
                {
                    "datetime": "2025-11-09 12:00:00",
                    "temp": 29.2,
                    "humidity": 70,
                    "rain_prob": 0.3,
                    "rain_volume": 2.5,
                    "description": "light rain"
                },
                ...
            ]
        """
        try:
            url = f"{self.base_url}/forecast"
            params = {
                'q': location,
                'appid': self.api_key,
                'units': 'metric',
                'lang': 'vi',
                'cnt': days * 8  # 8 forecasts per day (every 3h)
            }
            
            response = requests.get(url, params=params, timeout=10)
            data = response.json()
            
            if response.status_code != 200:
                raise Exception(f"API Error: {data.get('message', 'Unknown error')}")
            
            # Parse forecast
            forecast = []
            for item in data['list']:
                forecast.append({
                    'datetime': item['dt_txt'],
                    'timestamp': datetime.fromtimestamp(item['dt']),
                    'temp': item['main']['temp'],
                    'humidity': item['main']['humidity'],
                    'rain_prob': item.get('pop', 0),  # Probability of precipitation
                    'rain_volume': item.get('rain', {}).get('3h', 0),  # mm in 3h
                    'description': item['weather'][0]['description'],
                    'clouds': item['clouds']['all']
                })
            
            print(f"📅 Forecast for next {days} days:")
            for f in forecast[:3]:
                print(f"   {f['datetime']}: {f['temp']}°C, Rain: {f['rain_prob']*100:.0f}%")
            
            return forecast
            
        except Exception as e:
            print(f"❌ Forecast API Error: {e}")
            return []
    
    def analyze_irrigation_impact(self, forecast):
        """
        Phân tích impact của thời tiết lên lịch tưới
        
        Logic:
        - Nếu có mưa > 5mm trong 6h tới → Skip tưới
        - Nếu xác suất mưa > 70% → Delay tưới
        - Nếu nhiệt độ cao + độ ẩm thấp → Tưới nhiều hơn
        
        Returns:
            {
                "should_skip": True/False,
                "reason": "...",
                "rain_probability": 80,
                "rain_volume_6h": 12.5,
                "recommendation": "..."
            }
        """
        if not forecast:
            return {
                'should_skip': False,
                'reason': 'No forecast data available',
                'rain_probability': 0,
                'rain_volume_6h': 0,
                'recommendation': 'Proceed with normal schedule'
            }
        
        # Analyze next 6 hours (2 forecast items, each 3h)
        next_6h = forecast[:2]
        
        # Calculate metrics
        max_rain_prob = max(f['rain_prob'] for f in next_6h)
        total_rain = sum(f['rain_volume'] for f in next_6h)
        avg_temp = sum(f['temp'] for f in next_6h) / len(next_6h)
        avg_humidity = sum(f['humidity'] for f in next_6h) / len(next_6h)
        
        # Decision logic
        should_skip = False
        reason = ""
        recommendation = ""
        
        if total_rain > 5:
            should_skip = True
            reason = f"Dự báo mưa {total_rain:.1f}mm trong 6h tới"
            recommendation = "Tạm ngừng tưới, đợi sau mưa"
            
        elif max_rain_prob > 0.7:
            should_skip = True
            reason = f"Xác suất mưa cao ({max_rain_prob*100:.0f}%)"
            recommendation = "Delay tưới 3-6 giờ"
            
        elif avg_temp > 35 and avg_humidity < 50:
            should_skip = False
            reason = "Thời tiết nóng khô"
            recommendation = "Tăng thời gian tưới lên 20%"
            
        else:
            should_skip = False
            reason = "Thời tiết bình thường"
            recommendation = "Tưới theo lịch thông thường"
        
        result = {
            'should_skip': should_skip,
            'reason': reason,
            'rain_probability': int(max_rain_prob * 100),
            'rain_volume_6h': round(total_rain, 1),
            'avg_temp': round(avg_temp, 1),
            'avg_humidity': round(avg_humidity, 1),
            'recommendation': recommendation
        }
        
        print(f"\n🌦️ Irrigation Impact Analysis:")
        print(f"   Should skip: {should_skip}")
        print(f"   Reason: {reason}")
        print(f"   Recommendation: {recommendation}")
        
        return result
    
    def get_evapotranspiration_estimate(self, forecast):
        """
        Ước tính lượng nước bay hơi (ET0)
        Simplified Penman-Monteith equation
        
        Returns:
            ET0 in mm/day
        """
        if not forecast:
            return 0
        
        # Get daily average
        temp = sum(f['temp'] for f in forecast[:8]) / 8  # 24h average
        humidity = sum(f['humidity'] for f in forecast[:8]) / 8
        
        # Simplified ET0 calculation
        # ET0 ≈ 0.0023 × (Tmean + 17.8) × (Tmax - Tmin)^0.5
        # For simplicity, use rule of thumb: ~5mm/day in tropical climate
        
        base_et0 = 5.0  # mm/day baseline
        
        # Adjust for temperature (higher temp → more evaporation)
        temp_factor = 1 + (temp - 28) * 0.1  # +10% per degree above 28°C
        
        # Adjust for humidity (lower humidity → more evaporation)
        humidity_factor = 1 + (70 - humidity) * 0.01  # +1% per % below 70%
        
        et0 = base_et0 * temp_factor * humidity_factor
        et0 = max(3, min(10, et0))  # Clamp between 3-10 mm/day
        
        print(f"💧 Estimated ET0: {et0:.1f} mm/day")
        
        return round(et0, 2)


# ============================================
# SMART WATERING CALCULATOR
# ============================================

class SmartWateringCalculator:
    """
    Tính toán lượng nước cần tưới dựa trên:
    - Độ ẩm hiện tại và dự đoán
    - Thời tiết (mưa, nhiệt độ, độ ẩm)
    - Evapotranspiration
    - Loại cây
    """
    
    def __init__(self, weather_service):
        self.weather = weather_service
        
        # Plant water requirements (mm/day)
        self.plant_requirements = {
            'vegetables': 5.0,    # Rau
            'flowers': 6.0,       # Hoa
            'fruit_trees': 8.0,   # Cây ăn quả
            'grass': 4.0          # Cỏ
        }
    
    def calculate_water_need(self, 
                            current_soil_moisture, 
                            predicted_soil_moisture,
                            plant_type='vegetables',
                            location='Ho Chi Minh City'):
        """
        Tính lượng nước cần tưới
        
        Returns:
            {
                "water_needed_mm": 5.2,
                "duration_minutes": 15,
                "reasoning": [...],
                "confidence": 0.85
            }
        """
        reasoning = []
        
        # 1. Soil moisture deficit
        target_moisture = 60  # Target: 60%
        current_deficit = max(0, target_moisture - current_soil_moisture)
        predicted_deficit = max(0, target_moisture - predicted_soil_moisture)
        
        reasoning.append(f"Độ ẩm hiện tại: {current_soil_moisture:.1f}% (thiếu {current_deficit:.1f}%)")
        
        # 2. Get weather impact
        forecast = self.weather.get_forecast(location, days=1)
        impact = self.weather.analyze_irrigation_impact(forecast)
        
        if impact['should_skip']:
            reasoning.append(f"⚠️ {impact['reason']}")
            return {
                'water_needed_mm': 0,
                'duration_minutes': 0,
                'reasoning': reasoning,
                'recommendation': impact['recommendation'],
                'confidence': 0.9
            }
        
        # 3. Calculate ET0
        et0 = self.weather.get_evapotranspiration_estimate(forecast)
        reasoning.append(f"Lượng nước bay hơi: {et0:.1f} mm/ngày")
        
        # 4. Plant water requirement
        plant_req = self.plant_requirements.get(plant_type, 5.0)
        reasoning.append(f"Nhu cầu nước cây {plant_type}: {plant_req:.1f} mm/ngày")
        
        # 5. Calculate total water needed
        # Water needed = Soil deficit + ET0 + Plant requirement - Rain
        water_needed = (
            current_deficit * 0.5 +  # Convert % to mm (rough estimate)
            et0 * 0.5 +              # Half day ET0
            plant_req * 0.5 -        # Half day requirement
            impact['rain_volume_6h']
        )
        
        water_needed = max(0, water_needed)  # Cannot be negative
        
        # 6. Convert to irrigation duration
        # Assume: 1mm = 1 liter/m² and pump rate = 10 liter/min for 10m² area
        # So: 1mm needs 1 minute
        duration = int(water_needed)
        
        reasoning.append(f"💧 Lượng nước cần: {water_needed:.1f} mm = {duration} phút")
        
        return {
            'water_needed_mm': round(water_needed, 2),
            'duration_minutes': duration,
            'reasoning': reasoning,
            'recommendation': f"Tưới {duration} phút",
            'confidence': 0.85
        }


# ============================================
# USAGE EXAMPLE
# ============================================

if __name__ == "__main__":
    # Initialize service
    weather = WeatherService(api_key='YOUR_API_KEY_HERE')
    
    # Get current weather
    current = weather.get_current('Ho Chi Minh City')
    
    # Get forecast
    forecast = weather.get_forecast('Ho Chi Minh City', days=2)
    
    # Analyze impact
    impact = weather.analyze_irrigation_impact(forecast)
    
    # Calculate water need
    calculator = SmartWateringCalculator(weather)
    water_plan = calculator.calculate_water_need(
        current_soil_moisture=45.5,
        predicted_soil_moisture=42.0,
        plant_type='vegetables',
        location='Ho Chi Minh City'
    )
    
    print("\n📋 Watering Plan:")
    print(f"   Water needed: {water_plan['water_needed_mm']} mm")
    print(f"   Duration: {water_plan['duration_minutes']} minutes")
    print(f"   Recommendation: {water_plan['recommendation']}")