#!/usr/bin/env python3
"""
Dashboard Generator for Raspberry Pi Kiosk
Fetches data from various sources and generates a static HTML dashboard
"""

import os
import sys
import json
import logging
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

import requests
import feedparser
from jinja2 import Environment, FileSystemLoader
from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

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


class GoogleCalendarService:
    """Service for Google Calendar API interactions"""

    SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']

    def __init__(self):
        self.credentials = None
        self.service = None
        self._authenticate()

    def _authenticate(self):
        """Authenticate with Google Calendar API"""
        creds_file = 'token.json'

        # Load existing credentials
        if os.path.exists(creds_file):
            self.credentials = Credentials.from_authorized_user_file(creds_file, self.SCOPES)

        # If credentials are invalid or don't exist, get new ones
        if not self.credentials or not self.credentials.valid:
            if self.credentials and self.credentials.expired and self.credentials.refresh_token:
                try:
                    self.credentials.refresh(Request())
                except Exception as e:
                    logger.warning(f"Failed to refresh credentials: {e}")
                    self.credentials = None

            if not self.credentials:
                # Check for required environment variables
                client_id = os.getenv('GOOGLE_CALENDAR_CLIENT_ID')
                client_secret = os.getenv('GOOGLE_CALENDAR_CLIENT_SECRET')

                if not client_id or not client_secret:
                    logger.error("GOOGLE_CALENDAR_CLIENT_ID and GOOGLE_CALENDAR_CLIENT_SECRET must be set in environment variables")
                    logger.error(f"Current values - CLIENT_ID: {'<set>' if client_id else '<missing>'}, CLIENT_SECRET: {'<set>' if client_secret else '<missing>'}")
                    raise ValueError("Required Google Calendar credentials not found in environment variables")

                # Create proper client configuration for installed app
                client_config = {
                    "installed": {
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token",
                        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                        "redirect_uris": ["http://localhost:8081"],
                    }
                }

                try:
                    flow = InstalledAppFlow.from_client_config(client_config, self.SCOPES)
                    # Use fixed port 8080 to match redirect URI
                    logger.info("Starting OAuth flow - please complete authorization in your browser")
                    self.credentials = flow.run_local_server(port=8081, open_browser=True)
                    logger.info("OAuth flow completed successfully")

                    # Save credentials for next run
                    with open(creds_file, 'w') as token:
                        token.write(self.credentials.to_json())

                except Exception as e:
                    logger.error(f"OAuth flow failed: {e}")
                    logger.error("Make sure http://localhost:8081 is registered as a redirect URI in Google Cloud Console")
                    logger.error(f"OAuth client config: client_id ends with ...{client_id[-10:] if client_id and len(client_id) > 10 else 'N/A'}")
                    raise

        if self.credentials:
            try:
                self.service = build('calendar', 'v3', credentials=self.credentials)
                logger.info("Google Calendar service initialized successfully")
            except Exception as e:
                logger.error(f"Failed to build calendar service: {e}")
                self.service = None

    def get_events(self, calendar_id='primary', max_results=10) -> List[Dict]:
        """Fetch upcoming events from Google Calendar"""
        if not self.service:
            logger.error("Calendar service not authenticated")
            return []

        try:
            # Get events from now to end of day
            now = datetime.utcnow()
            end_of_day = now.replace(hour=23, minute=59, second=59, microsecond=999999)

            events_result = self.service.events().list(
                calendarId=calendar_id,
                timeMin=now.isoformat() + 'Z',
                timeMax=end_of_day.isoformat() + 'Z',
                maxResults=max_results,
                singleEvents=True,
                orderBy='startTime'
            ).execute()

            events = events_result.get('items', [])
            formatted_events = []

            for event in events:
                start = event['start'].get('dateTime', event['start'].get('date'))
                end = event['end'].get('dateTime', event['end'].get('date'))

                # Parse datetime
                if 'T' in start:
                    start_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
                    end_dt = datetime.fromisoformat(end.replace('Z', '+00:00'))
                    start_time = start_dt.strftime('%H:%M')
                    end_time = end_dt.strftime('%H:%M')
                else:
                    # All-day event
                    start_time = 'All Day'
                    end_time = ''

                formatted_events.append({
                    'summary': event.get('summary', 'Untitled Event'),
                    'start': start_time,
                    'end': end_time,
                    'location': event.get('location', ''),
                    'description': event.get('description', '')
                })

            return formatted_events

        except Exception as e:
            logger.error(f"Failed to fetch calendar events: {e}")
            return []

    def get_week_events(self, calendar_id='primary') -> Dict[str, Dict]:
        """Fetch events for current week (Monday-Sunday)"""
        if not self.service:
            logger.error("Calendar service not authenticated")
            return {}

        try:
            # Calculate Monday of current week
            now = datetime.now()
            monday = now - timedelta(days=now.weekday())
            monday = monday.replace(hour=0, minute=0, second=0, microsecond=0)
            
            # Calculate Sunday (end of week)
            sunday = monday + timedelta(days=6, hours=23, minutes=59, seconds=59)

            # Convert to UTC for API call
            monday_utc = monday.replace(tzinfo=timezone.utc)
            sunday_utc = sunday.replace(tzinfo=timezone.utc)

            events_result = self.service.events().list(
                calendarId=calendar_id,
                timeMin=monday_utc.isoformat(),
                timeMax=sunday_utc.isoformat(),
                maxResults=50,
                singleEvents=True,
                orderBy='startTime'
            ).execute()

            events = events_result.get('items', [])
            week_events = {}

            # Initialize week structure
            for i in range(7):
                day = monday + timedelta(days=i)
                date_key = day.strftime('%Y-%m-%d')
                week_events[date_key] = {
                    'date': day,
                    'day_name': ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'][i],
                    'day_number': day.day,
                    'is_today': day.date() == now.date(),
                    'all_day': [],
                    'timed': []
                }

            # Process events
            for event in events:
                start = event['start'].get('dateTime', event['start'].get('date'))
                end = event['end'].get('dateTime', event['end'].get('date'))
                
                # Determine event date
                if 'T' in start:
                    # Timed event
                    start_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
                    end_dt = datetime.fromisoformat(end.replace('Z', '+00:00'))
                    event_date = start_dt.date()
                    
                    event_data = {
                        'summary': event.get('summary', 'Untitled Event'),
                        'start': start_dt.strftime('%H:%M'),
                        'end': end_dt.strftime('%H:%M'),
                        'location': event.get('location', ''),
                        'type': 'timed'
                    }
                    
                    date_key = event_date.strftime('%Y-%m-%d')
                    if date_key in week_events:
                        week_events[date_key]['timed'].append(event_data)
                else:
                    # All-day event
                    event_date = datetime.fromisoformat(start).date()
                    
                    event_data = {
                        'summary': event.get('summary', 'Untitled Event'),
                        'location': event.get('location', ''),
                        'type': 'all_day'
                    }
                    
                    date_key = event_date.strftime('%Y-%m-%d')
                    if date_key in week_events:
                        week_events[date_key]['all_day'].append(event_data)

            return week_events

        except Exception as e:
            logger.error(f"Failed to fetch week calendar events: {e}")
            return {}


class DashboardGenerator:
    """Main dashboard generator class"""

    def __init__(self, config_path: str = "src/config/config.json"):
        """Initialize the dashboard generator with configuration"""
        self.config = self._load_config(config_path)
        self.template_dir = Path("src/templates")
        self.static_dir = Path("src/static")
        self.output_dir = Path("output")
        self.output_dir.mkdir(exist_ok=True)
        self.output_static_dir = self.output_dir / "static"
        self.output_static_dir.mkdir(exist_ok=True)
        self.calendar_service = None
        if not self.config.get('calendar', {}).get('use_mock_data', True):
            try:
                self.calendar_service = GoogleCalendarService()
            except Exception as e:
                logger.warning(f"Failed to initialize Google Calendar service: {e}")

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
                'sunset': datetime.fromtimestamp(data['sys']['sunset']).strftime('%H:%M'),
                'uv_index': 6  # Mock UV index since one-call API needed for real UV data
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
        """Fetch calendar events from Google Calendar or return mock data"""
        calendar_config = self.config.get('calendar', {})

        # Use real Google Calendar if configured
        if not calendar_config.get('use_mock_data', True) and self.calendar_service:
            try:
                calendar_id = calendar_config.get('calendar_id', 'primary')
                max_events = calendar_config.get('max_events', 5)
                events = self.calendar_service.get_events(calendar_id, max_events)
                logger.info(f"Fetched {len(events)} events from Google Calendar")
                return events
            except Exception as e:
                logger.error(f"Failed to fetch Google Calendar events: {e}")
                # Fall back to mock data on error

        # Return mock data as fallback
        logger.info("Using mock calendar data")
        return [
            {'summary': 'Team Standup', 'start': '09:00', 'end': '09:30'},
            {'summary': 'Project Review', 'start': '14:00', 'end': '15:00'},
            {'summary': 'Client Call', 'start': '16:00', 'end': '17:00'}
        ]

    def fetch_week_calendar_events(self) -> Dict[str, Dict]:
        """Fetch week calendar events from Google Calendar or return mock data"""
        calendar_config = self.config.get('calendar', {})

        # Use real Google Calendar if configured
        if not calendar_config.get('use_mock_data', True) and self.calendar_service:
            try:
                calendar_id = calendar_config.get('calendar_id', 'primary')
                week_events = self.calendar_service.get_week_events(calendar_id)
                logger.info(f"Fetched week events from Google Calendar")
                return week_events
            except Exception as e:
                logger.error(f"Failed to fetch Google Calendar week events: {e}")
                # Fall back to mock data on error

        # Return mock data as fallback for current week
        logger.info("Using mock week calendar data")
        now = datetime.now()
        monday = now - timedelta(days=now.weekday())
        
        mock_week_events = {}
        for i in range(7):
            day = monday + timedelta(days=i)
            date_key = day.strftime('%Y-%m-%d')
            mock_week_events[date_key] = {
                'date': day,
                'day_name': ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'][i],
                'day_number': day.day,
                'is_today': day.date() == now.date(),
                'all_day': [],
                'timed': []
            }

        # Add some mock events
        today_key = now.strftime('%Y-%m-%d')
        tomorrow = now + timedelta(days=1)
        tomorrow_key = tomorrow.strftime('%Y-%m-%d')
        
        if today_key in mock_week_events:
            mock_week_events[today_key]['timed'].extend([
                {'summary': 'Team Standup', 'start': '09:00', 'end': '09:30', 'type': 'timed'},
                {'summary': 'Project Review', 'start': '14:00', 'end': '15:00', 'type': 'timed'}
            ])
            mock_week_events[today_key]['all_day'].append(
                {'summary': 'Holiday', 'type': 'all_day'}
            )
        
        if tomorrow_key in mock_week_events:
            mock_week_events[tomorrow_key]['timed'].append(
                {'summary': 'Client Call', 'start': '16:00', 'end': '17:00', 'type': 'timed'}
            )

        return mock_week_events

    def copy_static_files(self):
        """Copy static files to output directory"""
        try:
            if self.static_dir.exists():
                # Copy all files from src/static to output/static
                for file_path in self.static_dir.glob('*'):
                    if file_path.is_file():
                        dest_path = self.output_static_dir / file_path.name
                        shutil.copy2(file_path, dest_path)
                        logger.debug(f"Copied {file_path} to {dest_path}")
                logger.info(f"Static files copied to {self.output_static_dir}")
        except Exception as e:
            logger.error(f"Failed to copy static files: {e}")

    def generate_dashboard(self):
        """Generate the dashboard HTML"""
        try:
            # Copy static files first
            self.copy_static_files()
            
            # Fetch all data
            logger.info("Fetching dashboard data...")
            weather = self.fetch_weather()
            forecast = self.fetch_forecast()
            articles = self.fetch_rss_feeds()
            events = self.fetch_calendar_events()
            week_events = self.fetch_week_calendar_events()

            # Get current date/time info
            now = datetime.now()
            day_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
            month_names = ['January', 'February', 'March', 'April', 'May', 'June',
                          'July', 'August', 'September', 'October', 'November', 'December']

            # Calculate week info for calendar
            monday = now - timedelta(days=now.weekday())
            week_start_date = f"{month_names[monday.month - 1]} {monday.day}"
            current_month = month_names[now.month - 1]
            current_year = now.year
            week_number = now.isocalendar()[1]

            # Mock data for v2 template features
            air_quality = {'status': 'Good', 'aqi': 45}
            traffic = [
                {'route': 'I-40 East', 'time': '22 min', 'status': 'normal'},
                {'route': 'US-52 North', 'time': '28 min', 'status': 'slow'},
                {'route': 'Business 40', 'time': '35 min', 'status': 'heavy'}
            ]
            
            # Calculate sun position for arc (mock calculation)
            sun_position = 35  # percentage across arc
            
            # Create upcoming events for ticker
            upcoming_events = [
                {'date': 'Jul 4', 'summary': 'Independence Day'},
                {'date': 'Jul 15', 'summary': 'Company All-Hands Meeting'},
                {'date': 'Jul 20', 'summary': 'Team Building Retreat'},
                {'date': 'Jul 28', 'summary': 'Q3 Planning Workshop'}
            ]
            
            # Add UV level text
            uv_level = 'High' if weather and weather.get('uv_index', 6) > 5 else 'Moderate'
            
            # Generate calendar month days (simple mock for now)
            month_days = []
            import calendar as cal
            month_cal = cal.monthcalendar(now.year, now.month)
            
            for week in month_cal:
                for day in week:
                    if day == 0:
                        continue  # Skip empty days
                    month_days.append({
                        'number': day,
                        'is_today': day == now.day,
                        'is_other_month': False
                    })

            # Prepare template data
            template_data = {
                'weather': weather,
                'forecast': forecast,
                'articles': articles,
                'events': events,
                'week_events': week_events,
                'current_time': now.strftime('%H:%M'),
                'day_name': day_names[now.weekday()],
                'date_info': f"{month_names[now.month - 1]} {now.day}",
                'current_month': current_month,
                'current_year': current_year,
                'week_start_date': week_start_date,
                'week_number': week_number,
                'last_updated': now.strftime('%H:%M:%S'),
                'config': self.config.get('display', {}),
                # v2 template specific data
                'air_quality': air_quality,
                'traffic': traffic,
                'sun_position': sun_position,
                'upcoming_events': upcoming_events,
                'uv_level': uv_level,
                'month_days': month_days
            }

            # Render template
            logger.info("Rendering dashboard template...")
            env = Environment(loader=FileSystemLoader(self.template_dir))
            template = env.get_template('dashboard-v2.html')
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
