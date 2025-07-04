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
                'q': config.get('location', 'London,UK'),
                'appid': config['api_key'],
                'units': config.get('units', 'metric')
            }
            
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            return {
                'temp': round(data['main']['temp']),
                'feels_like': round(data['main']['feels_like']),
                'description': data['weather'][0]['description'].title(),
                'icon': data['weather'][0]['icon'],
                'humidity': data['main']['humidity'],
                'wind_speed': round(data['wind']['speed'] * 3.6, 1)  # Convert m/s to km/h
            }
        except requests.exceptions.RequestException as e:
            logger.error(f"Weather fetch failed: {e}")
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
            articles = self.fetch_rss_feeds()
            events = self.fetch_calendar_events()
            
            # Prepare template data
            template_data = {
                'weather': weather,
                'articles': articles,
                'events': events,
                'last_updated': datetime.now().strftime('%H:%M:%S'),
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