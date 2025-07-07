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
        # Use absolute path for token file for container compatibility
        script_dir = Path(__file__).resolve().parent
        project_root = script_dir.parent
        creds_file = project_root / 'token.json'

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
                    logger.warning("Google Calendar credentials not configured - using mock calendar data")
                    logger.info("To enable Google Calendar, set GOOGLE_CALENDAR_CLIENT_ID and GOOGLE_CALENDAR_CLIENT_SECRET")
                    self.service = None
                    return

                # Create proper client configuration for installed app
                client_config = {
                    "installed": {
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token",
                        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                        "redirect_uris": [f"http://localhost:{os.getenv('PORT', '8081')}"],
                    }
                }

                try:
                    flow = InstalledAppFlow.from_client_config(client_config, self.SCOPES)
                    # Use port from environment variable
                    port = int(os.getenv('PORT', '8081'))
                    logger.info("Starting OAuth flow - please complete authorization in your browser")
                    self.credentials = flow.run_local_server(port=port, open_browser=True)
                    logger.info("OAuth flow completed successfully")

                    # Save credentials for next run
                    with open(creds_file, 'w') as token:
                        token.write(self.credentials.to_json())

                except Exception as e:
                    logger.error(f"OAuth flow failed: {e}")
                    port = os.getenv('PORT', '8081')
                    logger.error(f"Make sure http://localhost:{port} is registered as a redirect URI in Google Cloud Console")
                    logger.error(f"OAuth client config: client_id ends with ...{client_id[-10:] if client_id and len(client_id) > 10 else 'N/A'}")
                    raise

        if self.credentials:
            try:
                self.service = build('calendar', 'v3', credentials=self.credentials)
                logger.info("Google Calendar service initialized successfully")
            except Exception as e:
                logger.error(f"Failed to build calendar service: {e}")
                self.service = None

    def get_events(self, calendar_id='primary', max_results=20) -> List[Dict]:
        """Fetch upcoming events from Google Calendar (start of today through next 7 days)"""
        if not self.service:
            logger.debug("Google Calendar not configured - returning empty events list")
            return []

        try:
            # Get events from start of today to 7 days ahead to capture all-day events and future events
            now = datetime.utcnow()
            start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
            seven_days_ahead = start_of_today + timedelta(days=7)

            events_result = self.service.events().list(
                calendarId=calendar_id,
                timeMin=start_of_today.isoformat() + 'Z',
                timeMax=seven_days_ahead.isoformat() + 'Z',
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

            logger.info(f"Successfully fetched {len(formatted_events)} calendar events")
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

    def get_agenda_events(self, calendar_id='primary') -> List[Dict]:
        """Fetch agenda events for the next 5 days"""
        if not self.service:
            logger.error("Calendar service not authenticated")
            return []

        try:
            # Get events from start of today to 5 days ahead
            now = datetime.utcnow()
            start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
            five_days_ahead = start_of_today + timedelta(days=5)

            events_result = self.service.events().list(
                calendarId=calendar_id,
                timeMin=start_of_today.isoformat() + 'Z',
                timeMax=five_days_ahead.isoformat() + 'Z',
                maxResults=50,
                singleEvents=True,
                orderBy='startTime'
            ).execute()

            events = events_result.get('items', [])
            agenda = []

            # Initialize agenda structure for next 5 days
            for i in range(5):
                day = datetime.now() + timedelta(days=i)
                day_name = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'][day.weekday()]

                if i == 0:
                    display_name = 'Today'
                elif i == 1:
                    display_name = 'Tomorrow'
                else:
                    display_name = day_name

                agenda_day = {
                    'date': day.strftime('%m/%d'),
                    'day_name': display_name,
                    'day_abbr': day_name[:3],
                    'is_today': i == 0,
                    'events': []
                }
                agenda.append(agenda_day)

            # Process events into agenda structure
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
                        'type': 'timed'
                    }
                else:
                    # All-day event
                    event_date = datetime.fromisoformat(start).date()

                    event_data = {
                        'summary': event.get('summary', 'Untitled Event'),
                        'start': 'All Day',
                        'end': '',
                        'type': 'all_day'
                    }

                # Find the matching agenda day
                today = datetime.now().date()
                days_ahead = (event_date - today).days

                if 0 <= days_ahead < 5:
                    agenda[days_ahead]['events'].append(event_data)

            return agenda

        except Exception as e:
            logger.error(f"Failed to fetch agenda calendar events: {e}")
            return []


class DashboardGenerator:
    """Main dashboard generator class"""

    def __init__(self, config_path: Optional[str] = None):
        """Initialize the dashboard generator with configuration"""
        # Set up paths relative to script location for container compatibility
        script_dir = Path(__file__).resolve().parent
        project_root = script_dir.parent

        if config_path is None:
            config_path = script_dir / "config" / "config.json"
        else:
            config_path = Path(config_path)

        self.config = self._load_config(config_path)
        self.template_dir = script_dir / "templates"
        self.static_dir = script_dir / "static"
        self.output_dir = project_root / "output"
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
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            config = {}

        # Ensure weather config exists
        if 'weather' not in config:
            config['weather'] = {}

        # Override with environment variables if present
        if os.getenv('OPENWEATHER_API_KEY'):
            config['weather']['api_key'] = os.getenv('OPENWEATHER_API_KEY')
        if os.getenv('WEATHER_LOCATION'):
            config['weather']['location'] = os.getenv('WEATHER_LOCATION')
        if os.getenv('WEATHER_UNITS'):
            config['weather']['units'] = os.getenv('WEATHER_UNITS')

        return config

    def _calculate_mock_uv_index(self) -> int:
        """Calculate realistic UV index based on time of day and season"""
        try:
            now = datetime.now()
            hour = now.hour
            month = now.month

            # Base UV for summer months (higher in June-August)
            if month in [6, 7, 8]:  # Summer
                base_uv = 8
            elif month in [4, 5, 9, 10]:  # Spring/Fall
                base_uv = 6
            else:  # Winter
                base_uv = 3

            # Time-based adjustment (peak at solar noon ~1PM)
            if 10 <= hour <= 16:  # Peak sun hours
                time_multiplier = 1.0
                if 12 <= hour <= 14:  # Solar noon peak
                    time_multiplier = 1.2
            elif 8 <= hour < 10 or 16 < hour <= 18:  # Morning/evening
                time_multiplier = 0.6
            else:  # Early morning/night
                time_multiplier = 0.1

            uv_index = int(base_uv * time_multiplier)
            return max(0, min(11, uv_index))  # Clamp to valid UV range

        except Exception:
            return 6  # Safe fallback

    def _calculate_sun_position(self, weather: Optional[Dict]) -> int:
        """Calculate sun position percentage across the arc based on current time and sunrise/sunset"""
        try:
            now = datetime.now()
            current_time = now.hour * 60 + now.minute  # Current time in minutes

            if weather and 'sunrise' in weather and 'sunset' in weather:
                # Parse sunrise and sunset times
                sunrise_parts = weather['sunrise'].split(':')
                sunset_parts = weather['sunset'].split(':')

                sunrise_minutes = int(sunrise_parts[0]) * 60 + int(sunrise_parts[1])
                sunset_minutes = int(sunset_parts[0]) * 60 + int(sunset_parts[1])

                # Calculate position percentage
                if current_time < sunrise_minutes:
                    # Before sunrise - sun is "below" the arc (0%)
                    return 0
                elif current_time > sunset_minutes:
                    # After sunset - sun is "below" the arc (100% but visually off)
                    return 100
                else:
                    # During daylight - calculate position along arc
                    daylight_duration = sunset_minutes - sunrise_minutes
                    elapsed_daylight = current_time - sunrise_minutes
                    position = int((elapsed_daylight / daylight_duration) * 100)
                    return max(5, min(95, position))  # Keep within visible arc bounds
            else:
                # Fallback calculation based on hour of day
                if 6 <= now.hour <= 20:  # Rough daylight hours
                    # Simple calculation: 6AM = 0%, 1PM = 50%, 8PM = 100%
                    progress = (now.hour - 6) / 14  # 14 hour span
                    return int(progress * 100)
                else:
                    return 0 if now.hour < 6 else 100

        except Exception as e:
            logger.debug(f"Sun position calculation failed: {e}")
            return 35  # Safe middle position

    def fetch_weather(self) -> Optional[Dict]:
        """Fetch weather data from OpenWeatherMap One Call API 3.0 with alerts"""
        try:
            config = self.config.get('weather', {})
            if not config.get('api_key'):
                logger.warning("No weather API key configured")
                return None

            # First get coordinates using geocoding API
            location = config.get('location', os.getenv('WEATHER_LOCATION', 'Winston-Salem,NC,US'))
            geocoding_url = "https://api.openweathermap.org/geo/1.0/direct"
            geo_params = {
                'q': location,
                'appid': config['api_key'],
                'limit': 1
            }

            geo_response = requests.get(geocoding_url, params=geo_params, timeout=10)
            geo_response.raise_for_status()
            geo_data = geo_response.json()

            if not geo_data:
                logger.warning(f"Could not find coordinates for location: {location}")
                return self._fetch_weather_fallback()

            lat, lon = geo_data[0]['lat'], geo_data[0]['lon']

            # Use One Call API 3.0 for weather data with alerts
            url = "https://api.openweathermap.org/data/3.0/onecall"
            params = {
                'lat': lat,
                'lon': lon,
                'appid': config['api_key'],
                'units': config.get('units', os.getenv('WEATHER_UNITS', 'imperial')),
                'exclude': 'minutely,hourly'  # Only get current, daily, and alerts
            }

            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            current = data['current']

            # Convert wind speed based on units
            units = config.get('units', os.getenv('WEATHER_UNITS', 'imperial'))
            if units == 'imperial':
                wind_speed = round(current['wind_speed'], 1)  # mph
                wind_unit = 'mph'
            else:
                wind_speed = round(current['wind_speed'] * 3.6, 1)  # Convert m/s to km/h
                wind_unit = 'km/h'

            # Process alerts if they exist
            alerts = []
            if 'alerts' in data:
                for alert in data['alerts']:
                    alerts.append({
                        'sender_name': alert.get('sender_name', 'Weather Service'),
                        'event': alert.get('event', 'Weather Alert'),
                        'start': datetime.fromtimestamp(alert['start']).strftime('%m/%d %H:%M'),
                        'end': datetime.fromtimestamp(alert['end']).strftime('%m/%d %H:%M'),
                        'description': alert.get('description', ''),
                        'tags': alert.get('tags', [])
                    })

            return {
                'temp': round(current['temp']),
                'feels_like': round(current['feels_like']),
                'description': current['weather'][0]['description'].title(),
                'icon': current['weather'][0]['icon'],
                'humidity': current['humidity'],
                'wind_speed': wind_speed,
                'wind_unit': wind_unit,
                'sunrise': datetime.fromtimestamp(current['sunrise']).strftime('%H:%M'),
                'sunset': datetime.fromtimestamp(current['sunset']).strftime('%H:%M'),
                'uv_index': round(current.get('uvi', 0)),
                'alerts': alerts
            }
        except requests.exceptions.RequestException as e:
            logger.error(f"Weather fetch failed: {e}")
            return self._fetch_weather_fallback()
        except Exception as e:
            logger.error(f"Unexpected error fetching weather: {e}")
            return self._fetch_weather_fallback()

    def _fetch_weather_fallback(self) -> Optional[Dict]:
        """Fallback weather fetching using current weather API"""
        try:
            config = self.config.get('weather', {})
            if not config.get('api_key'):
                return None

            url = "https://api.openweathermap.org/data/2.5/weather"
            params = {
                'q': config.get('location', os.getenv('WEATHER_LOCATION', 'Winston-Salem,NC,US')),
                'appid': config['api_key'],
                'units': config.get('units', os.getenv('WEATHER_UNITS', 'imperial'))
            }

            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            # Convert wind speed based on units
            units = config.get('units', os.getenv('WEATHER_UNITS', 'imperial'))
            if units == 'imperial':
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
                'uv_index': self._calculate_mock_uv_index(),
                'alerts': []  # No alerts in fallback
            }
        except requests.exceptions.RequestException as e:
            logger.error(f"Fallback weather fetch failed: {e}")
            return None

    def fetch_air_quality(self) -> Dict:
        """Fetch air quality data from OpenWeather Air Pollution API or return mock data"""
        try:
            config = self.config.get('weather', {})
            if not config.get('api_key'):
                logger.info("No weather API key configured, using mock air quality data")
                return self._get_mock_air_quality()

            # Use same location as weather for simplicity
            location = config.get('location', os.getenv('WEATHER_LOCATION', 'Winston-Salem,NC,US'))

            # First, get coordinates for the location using geocoding
            geocoding_url = "https://api.openweathermap.org/geo/1.0/direct"
            geo_params = {
                'q': location,
                'appid': config['api_key'],
                'limit': 1
            }

            geo_response = requests.get(geocoding_url, params=geo_params, timeout=10)
            geo_response.raise_for_status()
            geo_data = geo_response.json()

            if not geo_data:
                logger.warning(f"Could not find coordinates for location: {location}")
                return self._get_mock_air_quality()

            lat, lon = geo_data[0]['lat'], geo_data[0]['lon']

            # Now get air quality data using coordinates
            aqi_url = "https://api.openweathermap.org/data/2.5/air_pollution"
            aqi_params = {
                'lat': lat,
                'lon': lon,
                'appid': config['api_key']
            }

            aqi_response = requests.get(aqi_url, params=aqi_params, timeout=10)
            aqi_response.raise_for_status()
            aqi_data = aqi_response.json()

            # Extract air quality index and convert to status
            aqi_value = aqi_data['list'][0]['main']['aqi']
            aqi_status_map = {
                1: 'Good',
                2: 'Fair',
                3: 'Moderate',
                4: 'Poor',
                5: 'Very Poor'
            }

            return {
                'status': aqi_status_map.get(aqi_value, 'Unknown'),
                'aqi': aqi_value * 50  # Convert OpenWeather 1-5 scale to rough US AQI equivalent
            }

        except requests.exceptions.RequestException as e:
            logger.error(f"Air quality fetch failed: {e}")
            return self._get_mock_air_quality()
        except Exception as e:
            logger.error(f"Unexpected error fetching air quality: {e}")
            return self._get_mock_air_quality()

    def _get_mock_air_quality(self) -> Dict:
        """Generate realistic mock air quality data based on time and season"""
        try:
            now = datetime.now()
            hour = now.hour
            month = now.month

            # Base AQI varies by season and time
            if month in [6, 7, 8]:  # Summer - higher pollution due to heat
                base_aqi = 65
            elif month in [12, 1, 2]:  # Winter - higher due to heating
                base_aqi = 55
            else:  # Spring/Fall - generally better
                base_aqi = 40

            # Time-based variation (rush hours have higher pollution)
            if 7 <= hour <= 9 or 17 <= hour <= 19:  # Rush hours
                time_multiplier = 1.3
            elif 11 <= hour <= 15:  # Midday
                time_multiplier = 1.1
            else:  # Night/early morning
                time_multiplier = 0.8

            final_aqi = int(base_aqi * time_multiplier)

            # Determine status based on US AQI scale
            if final_aqi <= 50:
                status = 'Good'
            elif final_aqi <= 100:
                status = 'Moderate'
            elif final_aqi <= 150:
                status = 'Unhealthy for Sensitive Groups'
            else:
                status = 'Unhealthy'

            return {'status': status, 'aqi': final_aqi}

        except Exception:
            return {'status': 'Good', 'aqi': 45}  # Safe fallback


    def fetch_forecast(self) -> Optional[List[Dict]]:
        """Fetch 5-day weather forecast from OpenWeatherMap API"""
        try:
            config = self.config.get('weather', {})
            if not config.get('api_key'):
                logger.warning("No weather API key configured")
                return None

            url = "https://api.openweathermap.org/data/2.5/forecast"
            params = {
                'q': config.get('location', os.getenv('WEATHER_LOCATION', 'Winston-Salem,NC,US')),
                'appid': config['api_key'],
                'units': config.get('units', os.getenv('WEATHER_UNITS', 'imperial'))
            }

            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            # Process forecast data - group by day and get daily highs/lows
            forecast_days = {}
            day_names = ['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN']

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
                        day_name = day_names[dt.weekday()]

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
                # Cache successful results for fallback
                if events:
                    self._save_calendar_cache(events)
                logger.info(f"Fetched {len(events)} events from Google Calendar")
                return events
            except Exception as e:
                logger.error(f"Failed to fetch Google Calendar events: {e}")
                # Try to load from cache as fallback
                cached_events = self._load_calendar_cache()
                if cached_events:
                    logger.info(f"Using cached calendar events ({len(cached_events)} events)")
                    return cached_events
                # Fall back to mock data on error

        # Return mock data as fallback
        logger.info("Using mock calendar data")
        return [
            {'summary': 'Team Standup', 'start': '09:00', 'end': '09:30'},
            {'summary': 'Project Review', 'start': '14:00', 'end': '15:00'},
            {'summary': 'Client Call', 'start': '16:00', 'end': '17:00'}
        ]

    def fetch_agenda_events(self) -> List[Dict]:
        """Fetch agenda events for the next 5 days from Google Calendar or return mock data"""
        calendar_config = self.config.get('calendar', {})

        # Use real Google Calendar if configured
        if not calendar_config.get('use_mock_data', True) and self.calendar_service:
            try:
                calendar_id = calendar_config.get('calendar_id', 'primary')
                agenda_events = self.calendar_service.get_agenda_events(calendar_id)
                logger.info("Fetched agenda events from Google Calendar")
                return agenda_events
            except Exception as e:
                logger.error(f"Failed to fetch Google Calendar agenda events: {e}")

        # Return mock agenda data for next 5 days
        logger.info("Using mock agenda data")
        now = datetime.now()
        agenda = []

        for i in range(5):
            day = now + timedelta(days=i)
            day_name = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'][day.weekday()]

            # Today gets a special name
            if i == 0:
                display_name = 'Today'
            elif i == 1:
                display_name = 'Tomorrow'
            else:
                display_name = day_name

            agenda_day = {
                'date': day.strftime('%m/%d'),
                'day_name': display_name,
                'day_abbr': day_name[:3],
                'is_today': i == 0,
                'events': []
            }

            # Add mock events for some days
            if i == 0:  # Today
                agenda_day['events'] = [
                    {'summary': 'Do laundry', 'start': '21:00', 'end': '22:00', 'type': 'timed'},
                    {'summary': 'Monthly review', 'start': 'All Day', 'end': '', 'type': 'all_day'}
                ]
            elif i == 1:  # Tomorrow
                agenda_day['events'] = [
                    {'summary': 'Team Meeting', 'start': '10:00', 'end': '11:00', 'type': 'timed'}
                ]
            elif i == 3:  # Day after tomorrow + 1
                agenda_day['events'] = [
                    {'summary': 'Client Call', 'start': '14:00', 'end': '15:00', 'type': 'timed'},
                    {'summary': 'Deadline: Project X', 'start': 'All Day', 'end': '', 'type': 'all_day'}
                ]
            # Days 2 and 4 will have no events to test empty day display

            agenda.append(agenda_day)

        return agenda

    def fetch_week_calendar_events(self) -> Dict[str, Dict]:
        """Fetch week calendar events from Google Calendar or return mock data"""
        calendar_config = self.config.get('calendar', {})

        # Use real Google Calendar if configured
        if not calendar_config.get('use_mock_data', True) and self.calendar_service:
            try:
                calendar_id = calendar_config.get('calendar_id', 'primary')
                week_events = self.calendar_service.get_week_events(calendar_id)
                logger.info("Fetched week events from Google Calendar")
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

    def _format_events_for_ticker(self, events: List[Dict]) -> List[Dict]:
        """Format calendar events for the ticker display"""
        ticker_events = []

        try:
            # Get current date for date formatting
            now = datetime.now()

            for event in events:
                if not event.get('summary'):
                    continue

                # Create a simple date format for the ticker
                event_date = now.strftime('%b %d')

                # Try to parse the start time if it's available
                start_time = event.get('start', '')
                if start_time and start_time != 'All Day' and ':' in start_time:
                    # It's a timed event
                    event_date = f"{event_date} {start_time}"
                elif start_time == 'All Day':
                    # It's an all-day event
                    event_date = f"{event_date} (All Day)"

                ticker_events.append({
                    'date': event_date,
                    'summary': event['summary']
                })

                # Limit to 4 events for ticker performance
                if len(ticker_events) >= 4:
                    break

        except Exception as e:
            logger.error(f"Error formatting events for ticker: {e}")
            # Return fallback events if formatting fails
            return [
                {'date': 'Today', 'summary': 'Independence Day'},
                {'date': 'Jul 15', 'summary': 'Company All-Hands Meeting'},
                {'date': 'Jul 20', 'summary': 'Team Building Retreat'},
                {'date': 'Jul 28', 'summary': 'Q3 Planning Workshop'}
            ]

        # If no events found, return a single fallback
        if not ticker_events:
            ticker_events = [{'date': 'Today', 'summary': 'No events scheduled'}]

        return ticker_events

    def _save_calendar_cache(self, events: List[Dict]):
        """Save calendar events to cache file for fallback"""
        try:
            cache_file = Path('logs/calendar_cache.json')
            cache_data = {
                'timestamp': datetime.now().isoformat(),
                'events': events
            }
            with open(cache_file, 'w') as f:
                json.dump(cache_data, f, indent=2)
            logger.debug(f"Calendar cache saved with {len(events)} events")
        except Exception as e:
            logger.warning(f"Failed to save calendar cache: {e}")

    def _load_calendar_cache(self) -> List[Dict]:
        """Load calendar events from cache file"""
        try:
            cache_file = Path('logs/calendar_cache.json')
            if not cache_file.exists():
                return []

            with open(cache_file, 'r') as f:
                cache_data = json.load(f)

            # Check if cache is recent (within 24 hours)
            cache_time = datetime.fromisoformat(cache_data['timestamp'])
            if datetime.now() - cache_time > timedelta(hours=24):
                logger.info("Calendar cache is too old, ignoring")
                return []

            events = cache_data.get('events', [])
            logger.debug(f"Loaded {len(events)} events from calendar cache")
            return events

        except Exception as e:
            logger.warning(f"Failed to load calendar cache: {e}")
            return []

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
            agenda_events = self.fetch_agenda_events()

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

            # Air quality data (real or mock)
            air_quality = self.fetch_air_quality()
            
            # Traffic map configuration
            traffic_map = self.config.get('traffic_map', {
                'center_lat': 36.0999,
                'center_lng': -80.2442,
                'zoom': 12,
                'map_type': 'roadmap',
                'show_traffic': True
            })

            # Calculate sun position for arc (real calculation)
            sun_position = self._calculate_sun_position(weather)

            # Create upcoming events for ticker from real calendar data
            upcoming_events = self._format_events_for_ticker(events)

            # Add UV level text
            uv_level = 'High' if weather and weather.get('uv_index', 6) > 5 else 'Moderate'

            # Generate enhanced calendar month days with previous/next month days
            month_days = []
            import calendar as cal

            # Get calendar grid for current month
            month_cal = cal.monthcalendar(now.year, now.month)

            # Calculate previous and next month info
            if now.month == 1:
                prev_month, prev_year = 12, now.year - 1
            else:
                prev_month, prev_year = now.month - 1, now.year

            if now.month == 12:
                next_month, next_year = 1, now.year + 1
            else:
                next_month, next_year = now.month + 1, now.year

            # Get number of days in previous month
            prev_month_days = cal.monthrange(prev_year, prev_month)[1]

            # Calculate how many days from previous month to show
            first_week = month_cal[0]
            prev_month_start_day = prev_month_days - (6 - first_week.index(1)) if 1 in first_week else prev_month_days

            next_month_day = 1

            for week_idx, week in enumerate(month_cal):
                for day_idx, day in enumerate(week):
                    if day == 0:
                        # This is an empty slot, determine if it's previous or next month
                        if week_idx == 0:  # First week, so it's previous month
                            prev_day = prev_month_start_day + day_idx + 1
                            month_days.append({
                                'number': prev_day,
                                'is_today': False,
                                'is_other_month': True
                            })
                        else:  # Later weeks, so it's next month
                            month_days.append({
                                'number': next_month_day,
                                'is_today': False,
                                'is_other_month': True
                            })
                            next_month_day += 1
                    else:
                        # This is a day in current month
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
                'agenda_events': agenda_events,
                'current_time': now.strftime('%H:%M'),
                'day_name': day_names[now.weekday()],
                'date_info': f"{month_names[now.month - 1]} {now.day}",
                'current_month': current_month,
                'current_year': current_year,
                'week_start_date': week_start_date,
                'week_number': week_number,
                'last_updated': now.strftime('%H:%M:%S'),
                'cache_buster': int(now.timestamp()),
                'config': self.config.get('display', {}),
                # v2 template specific data
                'air_quality': air_quality,
                'traffic_map': traffic_map,
                'google_maps_api_key': os.getenv('GOOGLE_MAPS_API_KEY'),
                'sun_position': sun_position,
                'upcoming_events': upcoming_events,
                'uv_level': uv_level,
                'month_days': month_days
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
    import argparse
    import time
    import signal

    parser = argparse.ArgumentParser(description='Dashboard Generator')
    parser.add_argument('--loop', action='store_true',
                       help='Run continuously with periodic updates')
    parser.add_argument('--interval', type=int, default=900,
                       help='Update interval in seconds (default: 900)')
    args = parser.parse_args()

    generator = DashboardGenerator()

    if args.loop:
        logger.info(f"Starting dashboard generator in loop mode (interval: {args.interval}s)")

        # Set up signal handling for graceful shutdown
        def signal_handler(signum, frame):
            logger.info("Received shutdown signal, stopping...")
            sys.exit(0)

        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)

        # Main loop
        try:
            while True:
                try:
                    logger.info("Generating dashboard...")
                    success = generator.generate_dashboard()
                    if success:
                        logger.info("Dashboard generated successfully")
                    else:
                        logger.error("Dashboard generation failed")

                    logger.info(f"Waiting {args.interval} seconds until next update...")
                    time.sleep(args.interval)

                except KeyboardInterrupt:
                    logger.info("Keyboard interrupt received, shutting down...")
                    break
                except Exception as e:
                    logger.error(f"Error in loop: {e}")
                    logger.info("Waiting 60 seconds before retrying...")
                    time.sleep(60)

        except Exception as e:
            logger.error(f"Fatal error: {e}")
            sys.exit(1)

        logger.info("Dashboard generator stopped")
        sys.exit(0)
    else:
        # Single run mode
        success = generator.generate_dashboard()
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
