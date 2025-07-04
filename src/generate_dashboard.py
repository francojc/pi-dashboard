#!/usr/bin/env python3
"""
Dashboard Generator for Raspberry Pi Kiosk
Fetches data from various sources and generates a static HTML dashboard
"""

import os
import sys
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import requests
import feedparser
from jinja2 import Environment, FileSystemLoader
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Ensure logs directory exists
Path('logs').mkdir(exist_ok=True)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/dashboard.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class DashboardGenerator:
    """Main dashboard generator class"""

    def __init__(self, config_path: str = "src/config/config.json"):
        """Initialize the dashboard generator with configuration"""
        self.config = self._load_config(config_path)
        self.template_dir = Path("src/templates")
        self.output_dir = Path("output")
        self.output_dir.mkdir(exist_ok=True)

    def _load_config(self, config_path: str) -> dict:
        """Load configuration from JSON file"""
        try:
            with open(config_path, 'r') as f:
                config = json.load(f)
            # Override with environment variables if present
            if os.getenv('OPENWEATHER_API_KEY'):
                config['weather']['api_key'] = os.getenv('OPENWEATHER_API_KEY')
            return config
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            return {}

    def fetch_weather(self) -> Optional[Dict]:
        """Fetch weather data from OpenWeatherMap API"""
        try:
            config = self.config.get('weather', {})
            if not config.get('api_key'):
                logger.warning("No weather API key configured")
                return None

            url = "https://api.openweathermap.org/data/2.5/weather"
            params = {
                'q': config.get('location', 'Winston-Salem,NC'),
                'appid': config['api_key'],
                'units': config.get('units', 'imperial')
            }

            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            # Convert wind speed based on units
            if config.get('units') == 'imperial':
                wind_speed = round(data['wind']['speed'], 1)  # mph
                wind_unit = 'mph'
            else:
                wind_speed = round(data['wind']['speed'] * 3.6, 1)  # Convert m/s to km/h
                wind_unit = 'km/h'

            return {
                'temp': round(data['main']['temp']),
                'feels_like': round(data['main']['feels_like']),
                'description': data['weather'][0]['description'].title(),
                'icon': data['weather'][0]['icon'],
                'humidity': data['main']['humidity'],
                'wind_speed': wind_speed,
                'wind_unit': wind_unit,
                'sunrise': datetime.fromtimestamp(data['sys']['sunrise']).strftime('%H:%M'),
                'sunset': datetime.fromtimestamp(data['sys']['sunset']).strftime('%H:%M')
            }
        except requests.exceptions.RequestException as e:
            logger.error(f"Weather fetch failed: {e}")
            return None

    def fetch_forecast(self) -> Optional[List[Dict]]:
        """Fetch 5-day weather forecast from OpenWeatherMap API"""
        try:
            config = self.config.get('weather', {})
            if not config.get('api_key'):
                logger.warning("No weather API key configured")
                return None

            url = "https://api.openweathermap.org/data/2.5/forecast"
            params = {
                'q': config.get('location', 'Winston-Salem,NC'),
                'appid': config['api_key'],
                'units': config.get('units', 'imperial')
            }

            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            # Process forecast data - group by day and get daily highs/lows
            forecast_days = {}
            day_names = ['TODAY', 'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN']
            
            for item in data['list'][:40]:  # 5 days * 8 (3-hour intervals)
                dt = datetime.fromtimestamp(item['dt'])
                day_key = dt.strftime('%Y-%m-%d')
                
                if day_key not in forecast_days:
                    # Determine day name
                    today = datetime.now().date()
                    item_date = dt.date()
                    
                    if item_date == today:
                        day_name = 'TODAY'
                    else:
                        day_name = day_names[dt.weekday() + 1] if dt.weekday() < 6 else day_names[0]
                    
                    forecast_days[day_key] = {
                        'day': day_name,
                        'icon': item['weather'][0]['icon'],
                        'description': item['weather'][0]['description'],
                        'high': round(item['main']['temp']),
                        'low': round(item['main']['temp']),
                        'temps': [round(item['main']['temp'])]
                    }
                else:
                    # Update high/low and collect temps
                    temp = round(item['main']['temp'])
                    forecast_days[day_key]['temps'].append(temp)
                    forecast_days[day_key]['high'] = max(forecast_days[day_key]['high'], temp)
                    forecast_days[day_key]['low'] = min(forecast_days[day_key]['low'], temp)

            # Convert to list and return first 5 days
            forecast_list = []
            for day_data in list(forecast_days.values())[:5]:
                forecast_list.append({
                    'day': day_data['day'],
                    'icon': day_data['icon'],
                    'description': day_data['description'],
                    'high': day_data['high'],
                    'low': day_data['low']
                })

            return forecast_list

        except requests.exceptions.RequestException as e:
            logger.error(f"Forecast fetch failed: {e}")
            return None

    def fetch_rss_feeds(self) -> List[Dict]:
        """Fetch RSS feed entries"""
        all_articles = []
        feeds = self.config.get('rss_feeds', {})

        for name, url in feeds.items():
            try:
                logger.info(f"Fetching RSS feed: {name}")
                feed = feedparser.parse(url)

                # Get configured number of articles per feed
                max_items = self.config.get('rss_settings', {}).get('items_per_feed', 3)

                for entry in feed.entries[:max_items]:
                    all_articles.append({
                        'source': name,
                        'title': entry.title,
                        'link': entry.get('link', '#'),
                        'published': entry.get('published', ''),
                        'summary': entry.get('summary', '')[:200] + '...' if entry.get('summary') else ''
                    })
            except Exception as e:
                logger.error(f"Failed to fetch RSS feed {name}: {e}")

        return all_articles

    def fetch_calendar_events(self) -> List[Dict]:
        """Fetch calendar events - placeholder for now"""
        # This would integrate with Google Calendar API
        # For testing, return mock data
        if self.config.get('calendar', {}).get('use_mock_data', True):
            return [
                {'summary': 'Team Standup', 'start': '09:00', 'end': '09:30'},
                {'summary': 'Project Review', 'start': '14:00', 'end': '15:00'},
                {'summary': 'Client Call', 'start': '16:00', 'end': '17:00'}
            ]
        return []

    def generate_dashboard(self):
        """Generate the dashboard HTML"""
        try:
            # Fetch all data
            logger.info("Fetching dashboard data...")
            weather = self.fetch_weather()
            forecast = self.fetch_forecast()
            articles = self.fetch_rss_feeds()
            events = self.fetch_calendar_events()

            # Get current date/time info
            now = datetime.now()
            day_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
            month_names = ['January', 'February', 'March', 'April', 'May', 'June',
                          'July', 'August', 'September', 'October', 'November', 'December']

            # Prepare template data
            template_data = {
                'weather': weather,
                'forecast': forecast,
                'articles': articles,
                'events': events,
                'current_time': now.strftime('%H:%M'),
                'day_name': day_names[now.weekday()],
                'date_info': f"{month_names[now.month - 1]} {now.day}",
                'last_updated': now.strftime('%H:%M:%S'),
                'config': self.config.get('display', {})
            }

            # Render template
            logger.info("Rendering dashboard template...")
            env = Environment(loader=FileSystemLoader(self.template_dir))
            template = env.get_template('dashboard.html')
            html_content = template.render(template_data)

            # Write output
            output_path = self.output_dir / 'index.html'
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(html_content)

            logger.info(f"Dashboard generated successfully: {output_path}")
            return True

        except Exception as e:
            logger.error(f"Dashboard generation failed: {e}")
            return False


def main():
    """Main entry point"""
    generator = DashboardGenerator()
    success = generator.generate_dashboard()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
