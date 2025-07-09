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

    def get_events(self, calendar_id='primary', max_results=20, calendar_name=None, calendar_color=None) -> List[Dict]:
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
                    'description': event.get('description', ''),
                    'calendar_name': calendar_name or 'Calendar',
                    'calendar_color': calendar_color or '#4285F4',
                    'calendar_id': calendar_id
                })

            logger.info(f"Successfully fetched {len(formatted_events)} calendar events")
            return formatted_events

        except Exception as e:
            logger.error(f"Failed to fetch calendar events: {e}")
            return []

    def get_week_events(self, calendar_id='primary', calendar_name=None, calendar_color=None) -> Dict[str, Dict]:
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
                        'type': 'timed',
                        'calendar_name': calendar_name or 'Calendar',
                        'calendar_color': calendar_color or '#4285F4',
                        'calendar_id': calendar_id
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
                        'type': 'all_day',
                        'calendar_name': calendar_name or 'Calendar',
                        'calendar_color': calendar_color or '#4285F4',
                        'calendar_id': calendar_id
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


class CanvasService:
    """Service for Canvas LMS API interactions"""
    
    def __init__(self, config: Dict):
        """Initialize Canvas service with configuration"""
        self.config = config
        self.api_key = os.getenv('CANVAS_API_KEY')
        self.base_url = os.getenv('CANVAS_BASE_URL', 'https://wfu.instructure.com')
        if not self.base_url.endswith('/api/v1'):
            self.base_url = f"{self.base_url.rstrip('/')}/api/v1"
        
        if not self.api_key:
            logger.warning("Canvas API key not configured - using mock data")
        
    def _make_request(self, endpoint: str, params: Dict = None) -> Optional[Dict]:
        """Make authenticated request to Canvas API"""
        if not self.api_key:
            return None
            
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }
        
        try:
            url = f"{self.base_url}/{endpoint.lstrip('/')}"
            response = requests.get(url, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"Canvas API request failed: {e}")
            return None
    
    def fetch_assignments(self, days_ahead: int = 14) -> List[Dict]:
        """Fetch upcoming assignments from configured courses"""
        if self.config.get('use_mock_data', False) or not self.api_key:
            return self._get_mock_assignments()
        
        all_assignments = []
        courses = self.config.get('courses', [])
        max_assignments = self.config.get('max_assignments', 10)
        
        # Calculate date range
        now = datetime.now()
        end_date = now + timedelta(days=days_ahead)
        
        for course in courses:
            course_id = course.get('id')
            course_name = course.get('name', f'Course {course_id}')
            course_color = course.get('color', '#666666')
            
            if not course_id:
                continue
                
            assignments = self._make_request(f'courses/{course_id}/assignments', {
                'bucket': 'upcoming',
                'per_page': 50
            })
            
            if not assignments:
                continue
                
            for assignment in assignments:
                due_at = assignment.get('due_at')
                if not due_at:
                    continue
                    
                try:
                    due_date = datetime.fromisoformat(due_at.replace('Z', '+00:00'))
                    if now <= due_date <= end_date:
                        all_assignments.append({
                            'title': assignment.get('name', 'Untitled Assignment'),
                            'course_name': course_name,
                            'course_color': course_color,
                            'due_date': due_date.strftime('%m/%d %H:%M'),
                            'due_date_full': due_date,
                            'points_possible': assignment.get('points_possible'),
                            'submission_types': assignment.get('submission_types', []),
                            'html_url': assignment.get('html_url', ''),
                            'days_until_due': (due_date.date() - now.date()).days
                        })
                except ValueError as e:
                    logger.warning(f"Invalid date format in assignment: {e}")
                    continue
        
        # Sort by due date and limit results
        all_assignments.sort(key=lambda x: x['due_date_full'])
        return all_assignments[:max_assignments]
    
    def fetch_announcements(self) -> List[Dict]:
        """Fetch recent announcements from configured courses"""
        if self.config.get('use_mock_data', False) or not self.api_key:
            return self._get_mock_announcements()
        
        if not self.config.get('show_announcements', True):
            return []
        
        all_announcements = []
        courses = self.config.get('courses', [])
        max_announcements = self.config.get('max_announcements', 5)
        
        for course in courses:
            course_id = course.get('id')
            course_name = course.get('name', f'Course {course_id}')
            course_color = course.get('color', '#666666')
            
            if not course_id:
                continue
                
            announcements = self._make_request(f'courses/{course_id}/discussion_topics', {
                'only_announcements': 'true',
                'per_page': 10
            })
            
            if not announcements:
                continue
                
            for announcement in announcements:
                posted_at = announcement.get('posted_at')
                if posted_at:
                    try:
                        posted_date = datetime.fromisoformat(posted_at.replace('Z', '+00:00'))
                        all_announcements.append({
                            'title': announcement.get('title', 'Untitled Announcement'),
                            'course_name': course_name,
                            'course_color': course_color,
                            'posted_date': posted_date.strftime('%m/%d'),
                            'posted_date_full': posted_date,
                            'message': announcement.get('message', '')[:200] + '...' if announcement.get('message', '') else '',
                            'html_url': announcement.get('html_url', '')
                        })
                    except ValueError as e:
                        logger.warning(f"Invalid date format in announcement: {e}")
                        continue
        
        # Sort by posted date (newest first) and limit results
        all_announcements.sort(key=lambda x: x['posted_date_full'], reverse=True)
        return all_announcements[:max_announcements]
    
    def _get_mock_assignments(self) -> List[Dict]:
        """Generate mock assignment data for testing"""
        mock_assignments = [
            {
                'title': 'Spanish Composition Essay',
                'course_name': 'SPA 111-B',
                'course_color': '#E53935',
                'due_date': '01/15 23:59',
                'due_date_full': datetime.now() + timedelta(days=2),
                'points_possible': 100,
                'submission_types': ['online_text_entry'],
                'html_url': '#',
                'days_until_due': 2
            },
            {
                'title': 'Grammar Quiz 3',
                'course_name': 'SPA 212-B',
                'course_color': '#1E88E5',
                'due_date': '01/18 11:59',
                'due_date_full': datetime.now() + timedelta(days=5),
                'points_possible': 50,
                'submission_types': ['online_quiz'],
                'html_url': '#',
                'days_until_due': 5
            },
            {
                'title': 'Oral Presentation',
                'course_name': 'SPA 111-B',
                'course_color': '#E53935',
                'due_date': '01/22 10:00',
                'due_date_full': datetime.now() + timedelta(days=9),
                'points_possible': 75,
                'submission_types': ['media_recording'],
                'html_url': '#',
                'days_until_due': 9
            }
        ]
        logger.info("Using mock Canvas assignment data")
        return mock_assignments
    
    def _get_mock_announcements(self) -> List[Dict]:
        """Generate mock announcement data for testing"""
        mock_announcements = [
            {
                'title': 'Important: Quiz Date Change',
                'course_name': 'SPA 212-B',
                'course_color': '#1E88E5',
                'posted_date': '01/10',
                'posted_date_full': datetime.now() - timedelta(days=3),
                'message': 'Quiz 3 has been moved from Friday to Monday due to the weather forecast...',
                'html_url': '#'
            },
            {
                'title': 'Office Hours Update',
                'course_name': 'SPA 111-B',
                'course_color': '#E53935',
                'posted_date': '01/12',
                'posted_date_full': datetime.now() - timedelta(days=1),
                'message': 'My office hours for this week will be Tuesday 2-4pm instead of the usual Monday time...',
                'html_url': '#'
            }
        ]
        logger.info("Using mock Canvas announcement data")
        return mock_announcements

    def fetch_grading_queue(self) -> List[Dict]:
        """Fetch items needing grading from configured courses"""
        if self.config.get('use_mock_data', False) or not self.api_key:
            return self._get_mock_grading_queue()
        
        all_grading_items = []
        courses = self.config.get('courses', [])
        max_items = self.config.get('max_grading_items', 10)
        
        for course in courses:
            course_id = course.get('id')
            course_name = course.get('name', f'Course {course_id}')
            course_color = course.get('color', '#666666')
            
            if not course_id:
                continue
                
            # Get assignments needing grading
            assignments = self._make_request(f'courses/{course_id}/assignments', {
                'bucket': 'ungraded',
                'per_page': 50
            })
            
            if not assignments:
                continue
                
            for assignment in assignments:
                needs_grading = assignment.get('needs_grading_count', 0)
                if needs_grading > 0:
                    due_at = assignment.get('due_at')
                    due_date_str = 'No due date'
                    priority = 'low'
                    
                    if due_at:
                        try:
                            due_date = datetime.fromisoformat(due_at.replace('Z', '+00:00'))
                            due_date_str = due_date.strftime('%m/%d %H:%M')
                            days_until_due = (due_date.date() - datetime.now().date()).days
                            
                            # Set priority based on due date
                            if days_until_due <= 1:
                                priority = 'high'
                            elif days_until_due <= 3:
                                priority = 'medium'
                            else:
                                priority = 'low'
                        except ValueError:
                            pass
                    
                    # Build SpeedGrader URL
                    speedgrader_url = f"{self.base_url.replace('/api/v1', '')}/courses/{course_id}/gradebook/speed_grader?assignment_id={assignment.get('id')}"
                    
                    all_grading_items.append({
                        'title': assignment.get('name', 'Untitled Assignment'),
                        'course_name': course_name,
                        'course_color': course_color,
                        'submissions_count': needs_grading,
                        'due_date': due_date_str,
                        'priority': priority,
                        'speedgrader_url': speedgrader_url,
                        'assignment_type': 'assignment'
                    })
        
        # Sort by priority (high first), then by due date
        priority_order = {'high': 0, 'medium': 1, 'low': 2}
        all_grading_items.sort(key=lambda x: (priority_order.get(x['priority'], 3), x['due_date']))
        
        return all_grading_items[:max_items]

    def fetch_student_engagement(self) -> List[Dict]:
        """Fetch students who may need attention based on engagement metrics"""
        if self.config.get('use_mock_data', False) or not self.api_key:
            return self._get_mock_student_engagement()
        
        at_risk_students = []
        courses = self.config.get('courses', [])
        max_students = self.config.get('max_at_risk_students', 5)
        
        for course in courses:
            course_id = course.get('id')
            course_name = course.get('name', f'Course {course_id}')
            course_color = course.get('color', '#666666')
            
            if not course_id:
                continue
            
            # Get students in the course
            students = self._make_request(f'courses/{course_id}/users', {
                'enrollment_type[]': 'student',
                'per_page': 100
            })
            
            if not students:
                continue
            
            for student in students:
                student_id = student.get('id')
                student_name = student.get('name', 'Unknown Student')
                
                # Get student submissions to check for missing assignments
                submissions = self._make_request(f'courses/{course_id}/students/submissions', {
                    'student_ids[]': student_id,
                    'per_page': 50
                })
                
                if not submissions:
                    continue
                
                missing_count = 0
                late_count = 0
                
                for submission in submissions:
                    if submission.get('missing'):
                        missing_count += 1
                    elif submission.get('late'):
                        late_count += 1
                
                # Determine if student is at risk
                risk_indicators = []
                if missing_count >= 2:
                    risk_indicators.append(f"{missing_count} missing assignments")
                if late_count >= 3:
                    risk_indicators.append(f"{late_count} late submissions")
                
                if risk_indicators:
                    at_risk_students.append({
                        'name': student_name,
                        'course_name': course_name,
                        'course_color': course_color,
                        'risk_indicators': risk_indicators,
                        'missing_assignments': missing_count,
                        'late_assignments': late_count,
                        'student_url': f"{self.base_url.replace('/api/v1', '')}/courses/{course_id}/users/{student_id}"
                    })
        
        # Sort by risk level (missing assignments first, then late assignments)
        at_risk_students.sort(key=lambda x: (x['missing_assignments'], x['late_assignments']), reverse=True)
        
        return at_risk_students[:max_students]

    def fetch_discussion_hotspots(self) -> List[Dict]:
        """Fetch discussion topics with high activity needing instructor attention"""
        if self.config.get('use_mock_data', False) or not self.api_key:
            return self._get_mock_discussion_hotspots()
        
        active_discussions = []
        courses = self.config.get('courses', [])
        max_discussions = self.config.get('max_discussions', 5)
        
        for course in courses:
            course_id = course.get('id')
            course_name = course.get('name', f'Course {course_id}')
            course_color = course.get('color', '#666666')
            
            if not course_id:
                continue
            
            # Get discussion topics, excluding announcements
            discussions = self._make_request(f'courses/{course_id}/discussion_topics', {
                'only_announcements': 'false',
                'per_page': 20
            })
            
            if not discussions:
                continue
            
            for discussion in discussions:
                unread_count = discussion.get('unread_count', 0)
                discussion_count = discussion.get('discussion_count', 0)
                
                # Only show discussions with activity
                if unread_count > 0 or discussion_count > 5:
                    active_discussions.append({
                        'title': discussion.get('title', 'Untitled Discussion'),
                        'course_name': course_name,
                        'course_color': course_color,
                        'unread_count': unread_count,
                        'total_posts': discussion_count,
                        'activity_level': 'High' if unread_count > 3 else 'Medium' if unread_count > 1 else 'Low',
                        'discussion_url': discussion.get('html_url', ''),
                        'last_posted': discussion.get('last_reply_at', '')
                    })
        
        # Sort by activity level (unread count descending)
        active_discussions.sort(key=lambda x: x['unread_count'], reverse=True)
        
        return active_discussions[:max_discussions]

    def fetch_recent_assignment_performance(self) -> List[Dict]:
        """Fetch performance data for the most recent assignment"""
        if self.config.get('use_mock_data', False) or not self.api_key:
            return self._get_mock_assignment_performance()
        
        courses = self.config.get('courses', [])
        most_recent_assignment = None
        most_recent_date = None
        
        # Find the most recently due assignment across all courses
        for course in courses:
            course_id = course.get('id')
            course_name = course.get('name', f'Course {course_id}')
            course_color = course.get('color', '#666666')
            
            if not course_id:
                continue
            
            assignments = self._make_request(f'courses/{course_id}/assignments', {
                'bucket': 'past',
                'per_page': 10
            })
            
            if not assignments:
                continue
            
            for assignment in assignments:
                due_at = assignment.get('due_at')
                if due_at:
                    try:
                        due_date = datetime.fromisoformat(due_at.replace('Z', '+00:00'))
                        if not most_recent_date or due_date > most_recent_date:
                            most_recent_date = due_date
                            most_recent_assignment = {
                                'assignment': assignment,
                                'course_id': course_id,
                                'course_name': course_name,
                                'course_color': course_color
                            }
                    except ValueError:
                        continue
        
        if not most_recent_assignment:
            return []
        
        # Get submissions for the most recent assignment
        assignment_id = most_recent_assignment['assignment']['id']
        course_id = most_recent_assignment['course_id']
        
        submissions = self._make_request(f'courses/{course_id}/assignments/{assignment_id}/submissions', {
            'per_page': 100
        })
        
        if not submissions:
            return []
        
        # Calculate performance statistics
        scores = []
        late_count = 0
        missing_count = 0
        
        for submission in submissions:
            if submission.get('missing'):
                missing_count += 1
            elif submission.get('late'):
                late_count += 1
            
            score = submission.get('score')
            if score is not None:
                scores.append(score)
        
        if not scores:
            return []
        
        # Calculate grade distribution
        avg_score = sum(scores) / len(scores)
        max_score = max(scores)
        min_score = min(scores)
        
        # Simple grade distribution (A, B, C, D, F)
        points_possible = most_recent_assignment['assignment'].get('points_possible', 100)
        grade_distribution = {'A': 0, 'B': 0, 'C': 0, 'D': 0, 'F': 0}
        
        for score in scores:
            percentage = (score / points_possible) * 100 if points_possible > 0 else 0
            if percentage >= 90:
                grade_distribution['A'] += 1
            elif percentage >= 80:
                grade_distribution['B'] += 1
            elif percentage >= 70:
                grade_distribution['C'] += 1
            elif percentage >= 60:
                grade_distribution['D'] += 1
            else:
                grade_distribution['F'] += 1
        
        return [{
            'assignment_name': most_recent_assignment['assignment']['name'],
            'course_name': most_recent_assignment['course_name'],
            'course_color': most_recent_assignment['course_color'],
            'average_grade': round(avg_score, 1),
            'submitted_count': len(scores),
            'total_students': len(submissions),
            'grade_distribution': grade_distribution
        }]

    def _get_mock_grading_queue(self) -> List[Dict]:
        """Generate mock grading queue data for testing"""
        mock_items = [
            {
                'title': 'Essay Assignment 3',
                'course_name': 'SPA 111-B',
                'course_color': '#E53935',
                'submissions_count': 18,
                'due_date': '01/15 23:59',
                'priority': 'high',
                'speedgrader_url': '#',
                'assignment_type': 'assignment'
            },
            {
                'title': 'Quiz: Preterite vs Imperfect',
                'course_name': 'SPA 212-B',
                'course_color': '#1E88E5',
                'submissions_count': 12,
                'due_date': '01/14 11:59',
                'priority': 'high',
                'speedgrader_url': '#',
                'assignment_type': 'quiz'
            },
            {
                'title': 'Discussion: Cultural Perspectives',
                'course_name': 'SPA 111-B',
                'course_color': '#E53935',
                'submissions_count': 8,
                'due_date': '01/18 23:59',
                'priority': 'medium',
                'speedgrader_url': '#',
                'assignment_type': 'discussion'
            }
        ]
        logger.info("Using mock Canvas grading queue data")
        return mock_items

    def _get_mock_student_engagement(self) -> List[Dict]:
        """Generate mock student engagement data for testing"""
        mock_students = [
            {
                'name': 'Maria Garcia',
                'course_name': 'SPA 111-B',
                'course_color': '#E53935',
                'risk_indicators': ['3 missing assignments', '2 late submissions'],
                'missing_assignments': 3,
                'late_assignments': 2,
                'student_url': '#'
            },
            {
                'name': 'John Smith',
                'course_name': 'SPA 212-B',
                'course_color': '#1E88E5',
                'risk_indicators': ['2 missing assignments'],
                'missing_assignments': 2,
                'late_assignments': 0,
                'student_url': '#'
            },
            {
                'name': 'Ana Rodriguez',
                'course_name': 'SPA 111-B',
                'course_color': '#E53935',
                'risk_indicators': ['5 late submissions'],
                'missing_assignments': 0,
                'late_assignments': 5,
                'student_url': '#'
            }
        ]
        logger.info("Using mock Canvas student engagement data")
        return mock_students

    def _get_mock_discussion_hotspots(self) -> List[Dict]:
        """Generate mock discussion hotspots data for testing"""
        mock_discussions = [
            {
                'title': 'Questions about Final Project',
                'course_name': 'SPA 212-B',
                'course_color': '#1E88E5',
                'unread_count': 7,
                'total_posts': 24,
                'activity_level': 'High',
                'discussion_url': '#',
                'last_posted': '2025-01-13T14:30:00Z'
            },
            {
                'title': 'Grammar Help Thread',
                'course_name': 'SPA 111-B',
                'course_color': '#E53935',
                'unread_count': 3,
                'total_posts': 15,
                'activity_level': 'Medium',
                'discussion_url': '#',
                'last_posted': '2025-01-13T10:15:00Z'
            },
            {
                'title': 'Cultural Exchange Discussion',
                'course_name': 'SPA 111-B',
                'course_color': '#E53935',
                'unread_count': 2,
                'total_posts': 12,
                'activity_level': 'Medium',
                'discussion_url': '#',
                'last_posted': '2025-01-12T16:45:00Z'
            }
        ]
        logger.info("Using mock Canvas discussion hotspots data")
        return mock_discussions

    def _get_mock_assignment_performance(self) -> List[Dict]:
        """Generate mock assignment performance data for testing"""
        mock_performance = [
            {
                'assignment_name': 'Midterm Exam',
                'course_name': 'SPA 212-B',
                'course_color': '#1E88E5',
                'average_grade': 84.3,
                'submitted_count': 28,
                'total_students': 29,
                'grade_distribution': {
                    'A': 8,
                    'B': 12,
                    'C': 6,
                    'D': 2,
                    'F': 0
                }
            },
            {
                'assignment_name': 'Essay Assignment',
                'course_name': 'SPA 111-B',
                'course_color': '#E53935',
                'average_grade': 78.5,
                'submitted_count': 24,
                'total_students': 26,
                'grade_distribution': {
                    'A': 4,
                    'B': 10,
                    'C': 8,
                    'D': 2,
                    'F': 0
                }
            }
        ]
        logger.info("Using mock Canvas assignment performance data")
        return mock_performance


class MapboxService:
    """Service for Mapbox API interactions for traffic maps and travel times"""
    
    def __init__(self, config: Dict, api_key: str):
        """Initialize Mapbox service with configuration and API key"""
        self.config = config
        self.api_key = api_key
        self.base_url = "https://api.mapbox.com"
        self._cache = {}
        self._cache_time = None
        self.cache_duration = 300  # 5 minutes cache
        
    def get_map_config(self) -> Dict:
        """Generate Mapbox configuration for interactive traffic map"""
        try:
            center_lat = self.config.get('center_lat', 36.133269983139876)
            center_lng = self.config.get('center_lng', -80.27593704795439)
            zoom = self.config.get('zoom', 11)
            map_style = self.config.get('map_style', 'dark-v10')
            # Ensure full Mapbox style URL
            if not map_style.startswith('mapbox://'):
                map_style = f'mapbox://styles/mapbox/{map_style}'
            
            return {
                'access_token': self.api_key,
                'center': [center_lng, center_lat],
                'zoom': zoom,
                'style': map_style,
                'traffic_enabled': True
            }
            
        except Exception as e:
            logger.error(f"Failed to generate Mapbox config: {e}")
            return {}
    
    def get_travel_times(self, destinations: List[Dict]) -> List[Dict]:
        """Get travel times to destinations using Mapbox Matrix API"""
        try:
            # Check cache first
            if self._is_cache_valid():
                logger.debug("Using cached travel times")
                return self._cache.get('travel_times', [])
            
            if not destinations:
                return []
                
            home_location = self.config.get('home_location', {})
            home_lat = home_location.get('lat', 36.133269983139876)
            home_lng = home_location.get('lng', -80.27593704795439)
            
            # Build coordinates string: origin;destination1;destination2
            coordinates = f"{home_lng},{home_lat}"
            for dest in destinations:
                coordinates += f";{dest['lng']},{dest['lat']}"
            
            # Mapbox Matrix API for travel times with traffic
            matrix_url = (f"{self.base_url}/directions-matrix/v1/mapbox/driving-traffic/"
                         f"{coordinates}")
            
            params = {
                'access_token': self.api_key,
                'sources': '0',  # Origin (home) index
                'destinations': ';'.join(str(i+1) for i in range(len(destinations))),
                'annotations': 'duration'
            }
            
            logger.debug(f"Requesting travel times from Mapbox Matrix API")
            response = requests.get(matrix_url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            if 'durations' not in data or not data['durations']:
                logger.warning("No duration data in Mapbox response")
                return []
            
            # Process travel times
            travel_times = []
            durations = data['durations'][0]  # First row (from origin)
            
            for i, dest in enumerate(destinations):
                if i < len(durations) and durations[i] is not None:
                    duration_seconds = durations[i]
                    duration_minutes = round(duration_seconds / 60)
                    
                    # Determine traffic status based on duration
                    traffic_status = self._determine_traffic_status(duration_minutes)
                    
                    travel_times.append({
                        'destination': dest['name'],
                        'duration_minutes': duration_minutes,
                        'duration_text': f"{duration_minutes} min",
                        'traffic_status': traffic_status
                    })
                else:
                    travel_times.append({
                        'destination': dest['name'],
                        'duration_minutes': 0,
                        'duration_text': "N/A",
                        'traffic_status': "No data"
                    })
            
            # Cache results
            self._cache['travel_times'] = travel_times
            self._cache_time = datetime.now()
            
            logger.info(f"Retrieved travel times for {len(travel_times)} destinations")
            return travel_times
            
        except requests.RequestException as e:
            logger.error(f"Mapbox API request failed: {e}")
            return self._get_cached_or_fallback()
        except Exception as e:
            logger.error(f"Failed to get travel times: {e}")
            return self._get_cached_or_fallback()
    
    def _determine_traffic_status(self, duration_minutes: int) -> str:
        """Determine traffic status based on duration"""
        if duration_minutes <= 10:
            return "Light traffic"
        elif duration_minutes <= 20:
            return "Moderate traffic"
        elif duration_minutes <= 30:
            return "Heavy traffic"
        else:
            return "Severe traffic"
    
    def _is_cache_valid(self) -> bool:
        """Check if cached data is still valid"""
        if self._cache_time is None:
            return False
        return (datetime.now() - self._cache_time).seconds < self.cache_duration
    
    def _get_cached_or_fallback(self) -> List[Dict]:
        """Return cached data if available, otherwise return fallback"""
        if 'travel_times' in self._cache:
            logger.info("Using cached travel times due to API failure")
            return self._cache['travel_times']
        
        logger.warning("No cached data available, returning fallback")
        return [
            {
                'destination': 'Destination',
                'duration_minutes': 0,
                'duration_text': "No data",
                'traffic_status': "Service unavailable"
            }
        ]


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
        self.test_mode = False  # Will be set by command line args
        self.calendar_service = None
        if not self.config.get('calendar', {}).get('use_mock_data', True):
            try:
                self.calendar_service = GoogleCalendarService()
            except Exception as e:
                logger.warning(f"Failed to initialize Google Calendar service: {e}")
        
        # Initialize Mapbox service for traffic and travel times
        self.mapbox_service = None
        mapbox_api_key = os.getenv('MAPBOX_API_KEY')
        if mapbox_api_key:
            try:
                self.mapbox_service = MapboxService(self.config.get('traffic', {}), mapbox_api_key)
                logger.info("Mapbox service initialized successfully")
            except Exception as e:
                logger.warning(f"Failed to initialize Mapbox service: {e}")
        else:
            logger.warning("MAPBOX_API_KEY not found - traffic features will be limited")
        
        # Initialize Canvas service
        self.canvas_service = None
        try:
            self.canvas_service = CanvasService(self.config.get('canvas', {}))
            logger.info("Canvas service initialized successfully")
        except Exception as e:
            logger.warning(f"Failed to initialize Canvas service: {e}")

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
        # If in test mode, return mock data
        if self.test_mode:
            logger.info("Test mode: Using mock weather data")
            return self._get_mock_weather_data()
            
        try:
            config = self.config.get('weather', {})
            if not config.get('api_key'):
                logger.warning("No weather API key configured")
                return self._get_mock_weather_data()

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

            # Use free current weather API instead of One Call API (which requires subscription)
            url = "https://api.openweathermap.org/data/2.5/weather"
            params = {
                'lat': lat,
                'lon': lon,
                'appid': config['api_key'],
                'units': config.get('units', os.getenv('WEATHER_UNITS', 'imperial'))
            }

            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            current = data['main']

            # Convert wind speed based on units
            wind_data = data.get('wind', {})
            wind_speed = round(wind_data.get('speed', 0))
            units = config.get('units', os.getenv('WEATHER_UNITS', 'imperial'))
            if units == 'imperial':
                wind_unit = 'mph'
            elif units == 'metric':
                wind_unit = 'km/h'  
            else:
                wind_unit = 'm/s'

            # No alerts available in free current weather API
            alerts = []

            # Get hourly forecast from the free 5-day/3-hour forecast API
            hourly_forecast = self._fetch_hourly_from_forecast()

            return {
                'temp': round(current['temp']),
                'feels_like': round(current['feels_like']),
                'description': data['weather'][0]['description'].title(),
                'icon': data['weather'][0]['icon'],
                'humidity': current['humidity'],
                'wind_speed': wind_speed,
                'wind_unit': wind_unit,
                'sunrise': datetime.fromtimestamp(data['sys']['sunrise']).strftime('%H:%M'),
                'sunset': datetime.fromtimestamp(data['sys']['sunset']).strftime('%H:%M'),
                'uv_index': self._calculate_mock_uv_index(),
                'alerts': alerts,
                'hourly_forecast': hourly_forecast
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
                'alerts': [],  # No alerts in fallback
                'hourly_forecast': None  # No hourly data in fallback
            }
        except requests.exceptions.RequestException as e:
            logger.error(f"Fallback weather fetch failed: {e}")
            return None

    def _process_hourly_data(self, data: dict) -> Optional[List[Dict]]:
        """
        Processes the hourly forecast data from the One Call API response.
        Returns a list of dictionaries, each representing an hour's forecast.
        """
        from datetime import datetime, timezone, timedelta
        
        if "hourly" not in data or "timezone_offset" not in data:
            logger.info("Hourly forecast data not available in API response.")
            return None

        hourly_forecast = []
        local_tz = timezone(timedelta(seconds=data['timezone_offset']))

        for hour_data in data["hourly"]:
            # The 'weather' key contains a list; the primary weather is the first item.
            weather_info = hour_data['weather'][0] if hour_data.get('weather') else {}

            # Convert UTC timestamp ('dt') to local time using the provided offset.
            dt_object = datetime.fromtimestamp(hour_data['dt'], tz=local_tz)

            # The API provides 'pop' as a float from 0.0 to 1.0. Convert to a percentage.
            pop_percentage = int(hour_data.get('pop', 0) * 100)

            hourly_forecast.append({
                'time': dt_object.strftime('%-I %p').strip(),
                'temp': int(round(hour_data['temp'])),
                'humidity': hour_data['humidity'],
                'wind_speed': int(round(hour_data['wind_speed'])),
                'pop': pop_percentage,
                'description': weather_info.get('description', 'N/A').title(),
                'icon': weather_info.get('icon', '01d')  # Default to a 'clear sky' icon
            })
            
        return hourly_forecast

    def _fetch_hourly_from_forecast(self) -> Optional[List[Dict]]:
        """
        Fetch pseudo-hourly data from the free 5-day/3-hour forecast API.
        Returns data every 3 hours, which we'll present as "hourly" data.
        """
        try:
            config = self.config.get('weather', {})
            if not config.get('api_key'):
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

            hourly_forecast = []
            
            # Take first 8 items (24 hours worth of 3-hour intervals)
            for item in data['list'][:8]:
                # Convert UTC timestamp to local time
                dt_object = datetime.fromtimestamp(item['dt'])
                
                # Get weather info
                weather_info = item['weather'][0] if item.get('weather') else {}
                
                # Convert pop (probability of precipitation) to percentage
                pop_percentage = int(item.get('pop', 0) * 100)
                
                hourly_forecast.append({
                    'time': dt_object.strftime('%-I %p').strip(),
                    'temp': int(round(item['main']['temp'])),
                    'humidity': item['main']['humidity'],
                    'wind_speed': int(round(item.get('wind', {}).get('speed', 0))),
                    'pop': pop_percentage,
                    'description': weather_info.get('description', 'N/A').title(),
                    'icon': weather_info.get('icon', '01d')
                })
            
            return hourly_forecast
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Hourly forecast fetch failed: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error fetching hourly forecast: {e}")
            return None

    def _get_mock_weather_data(self) -> Dict:
        """Return mock weather data for testing"""
        return {
            'temp': 81,
            'feels_like': 87,
            'description': 'Clear Sky',
            'icon': '01d',
            'humidity': 65,
            'wind_speed': 8,
            'wind_unit': 'mph',
            'sunrise': '06:30',
            'sunset': '20:15',
            'uv_index': 7,
            'alerts': [],
            'hourly_forecast': [
                {'time': '9 AM', 'temp': 81, 'humidity': 65, 'wind_speed': 8, 'pop': 0, 'description': 'Clear Sky', 'icon': '01d'},
                {'time': '12 PM', 'temp': 85, 'humidity': 60, 'wind_speed': 10, 'pop': 5, 'description': 'Sunny', 'icon': '01d'},
                {'time': '3 PM', 'temp': 88, 'humidity': 55, 'wind_speed': 12, 'pop': 10, 'description': 'Partly Cloudy', 'icon': '02d'},
                {'time': '6 PM', 'temp': 85, 'humidity': 60, 'wind_speed': 8, 'pop': 15, 'description': 'Partly Cloudy', 'icon': '02d'},
                {'time': '9 PM', 'temp': 79, 'humidity': 70, 'wind_speed': 6, 'pop': 20, 'description': 'Clear', 'icon': '01n'},
                {'time': '12 AM', 'temp': 75, 'humidity': 75, 'wind_speed': 4, 'pop': 0, 'description': 'Clear', 'icon': '01n'},
                {'time': '3 AM', 'temp': 72, 'humidity': 80, 'wind_speed': 3, 'pop': 0, 'description': 'Clear', 'icon': '01n'},
                {'time': '6 AM', 'temp': 74, 'humidity': 78, 'wind_speed': 5, 'pop': 5, 'description': 'Sunny', 'icon': '01d'}
            ]
        }

    def _get_mock_calendar_events(self) -> List[Dict]:
        """Return mock calendar events for testing"""
        return [
            {'summary': 'Team Standup', 'start': '09:00', 'end': '09:30', 'calendar_name': 'Work', 'calendar_color': '#0F9D58'},
            {'summary': 'Project Review', 'start': '14:00', 'end': '15:00', 'calendar_name': 'Work', 'calendar_color': '#0F9D58'},
            {'summary': 'Client Call', 'start': '16:00', 'end': '17:00', 'calendar_name': 'Personal', 'calendar_color': '#4285F4'},
            {'summary': 'Monthly review', 'start': 'All Day', 'end': '', 'type': 'all_day', 'calendar_name': 'Personal', 'calendar_color': '#4285F4'}
        ]

    def _get_mock_agenda_events(self) -> List[Dict]:
        """Return mock agenda events for testing"""
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
                'date': f"{day.month}/{day.day}",
                'day_name': display_name,
                'day_abbr': day_name[:3],
                'is_today': i == 0,
                'events': []
            }

            # Add mock events for some days
            if i == 0:  # Today
                agenda_day['events'] = [
                    {'summary': 'Do laundry', 'start': '21:00', 'end': '22:00', 'type': 'timed', 'calendar_name': 'Personal', 'calendar_color': '#4285F4'},
                    {'summary': 'Monthly review', 'start': 'All Day', 'end': '', 'type': 'all_day', 'calendar_name': 'Work', 'calendar_color': '#0F9D58'}
                ]
            elif i == 1:  # Tomorrow
                agenda_day['events'] = [
                    {'summary': 'NCSU orientation', 'start': '08:30', 'end': '09:00', 'type': 'timed', 'calendar_name': 'Work', 'calendar_color': '#0F9D58'}
                ]
            elif i == 3:  # Day after tomorrow + 1
                agenda_day['events'] = [
                    {'summary': 'Client Call', 'start': '14:00', 'end': '15:00', 'type': 'timed', 'calendar_name': 'Work', 'calendar_color': '#0F9D58'},
                    {'summary': 'Deadline: Project X', 'start': 'All Day', 'end': '', 'type': 'all_day', 'calendar_name': 'Work', 'calendar_color': '#0F9D58'}
                ]
            # Days 2 and 4 will have no events to test empty day display

            agenda.append(agenda_day)

        return agenda

    def _get_mock_traffic_data(self) -> Dict:
        """Return mock traffic data for testing"""
        return {
            'map_config': {
                'access_token': 'mock_token',
                'style': 'mapbox://styles/mapbox/dark-v10',
                'center': [-80.27593704795439, 36.133269983139876],
                'zoom': 12
            },
            'travel_times': [
                {'destination': 'Downtown', 'duration_text': '12 mins', 'traffic_status': 'Light traffic'},
                {'destination': 'University', 'duration_text': '8 mins', 'traffic_status': 'Normal'},
                {'destination': 'Airport', 'duration_text': '25 mins', 'traffic_status': 'Moderate traffic'}
            ],
            'service': 'mock'
        }

    def _get_mock_forecast_data(self) -> List[Dict]:
        """Return mock forecast data for testing"""
        return [
            {'day': 'Today', 'high': 85, 'low': 68, 'description': 'Sunny', 'icon': '01d'},
            {'day': 'Tomorrow', 'high': 82, 'low': 65, 'description': 'Partly Cloudy', 'icon': '02d'},
            {'day': 'Thursday', 'high': 79, 'low': 62, 'description': 'Light Rain', 'icon': '10d'},
            {'day': 'Friday', 'high': 81, 'low': 64, 'description': 'Cloudy', 'icon': '04d'},
            {'day': 'Saturday', 'high': 84, 'low': 67, 'description': 'Sunny', 'icon': '01d'}
        ]

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
        # If in test mode, return mock data
        if self.test_mode:
            logger.info("Test mode: Using mock forecast data")
            return self._get_mock_forecast_data()
            
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

            # Convert to list and calculate temperature range for bars
            forecast_list = []
            for day_data in list(forecast_days.values())[:5]:
                forecast_list.append({
                    'day': day_data['day'],
                    'icon': day_data['icon'],
                    'description': day_data['description'],
                    'high': day_data['high'],
                    'low': day_data['low']
                })

            # Calculate week temperature range for bar visualization
            all_temps = []
            for day in forecast_list:
                all_temps.extend([day['high'], day['low']])
            
            if all_temps:
                week_temp_min = min(all_temps)
                week_temp_max = max(all_temps)
                week_temp_range = week_temp_max - week_temp_min
                
                # Ensure minimum range for visual differentiation
                if week_temp_range < 10:
                    week_temp_range = 10
                    week_temp_min = week_temp_max - 10
            else:
                week_temp_min = 60
                week_temp_range = 25

            # Add temperature range data to each forecast day
            for day in forecast_list:
                day['week_temp_min'] = week_temp_min
                day['week_temp_range'] = week_temp_range

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
        # If in test mode, return mock data immediately
        if self.test_mode:
            logger.info("Test mode: Using mock calendar data")
            return self._get_mock_calendar_events()
            
        calendar_config = self.config.get('calendar', {})

        # Use real Google Calendar if configured
        if not calendar_config.get('use_mock_data', True) and self.calendar_service:
            try:
                all_events = []
                
                # Handle both new multi-calendar config and legacy single calendar
                calendars = calendar_config.get('calendars', {})
                
                # Legacy fallback - convert old calendar_id to new format
                if not calendars and 'calendar_id' in calendar_config:
                    calendars = {
                        'primary': {
                            'id': calendar_config['calendar_id'],
                            'name': 'Calendar',
                            'color': '#4285F4',
                            'enabled': True
                        }
                    }
                elif not calendars and '_legacy_calendar_id' in calendar_config:
                    calendars = {
                        'primary': {
                            'id': calendar_config['_legacy_calendar_id'],
                            'name': 'Calendar', 
                            'color': '#4285F4',
                            'enabled': True
                        }
                    }

                max_events_per_calendar = calendar_config.get('max_events_per_calendar', calendar_config.get('max_events', 5))
                max_events_total = calendar_config.get('max_events_total', 15)

                # Fetch events from each enabled calendar
                for cal_key, cal_info in calendars.items():
                    if not cal_info.get('enabled', True):
                        continue
                    
                    try:
                        cal_events = self.calendar_service.get_events(
                            calendar_id=cal_info['id'],
                            max_results=max_events_per_calendar,
                            calendar_name=cal_info.get('name', cal_key),
                            calendar_color=cal_info.get('color', '#4285F4')
                        )
                        all_events.extend(cal_events)
                        logger.info(f"Fetched {len(cal_events)} events from calendar '{cal_info.get('name', cal_key)}'")
                    except Exception as e:
                        logger.error(f"Failed to fetch events from calendar '{cal_info.get('name', cal_key)}': {e}")

                # Sort all events by start time and limit total
                all_events.sort(key=lambda x: (x.get('start', ''), x.get('summary', '')))
                all_events = all_events[:max_events_total]

                # Cache successful results for fallback
                if all_events:
                    self._save_calendar_cache(all_events)
                logger.info(f"Total fetched events: {len(all_events)} from {len([c for c in calendars.values() if c.get('enabled', True)])} calendars")
                return all_events
                
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
        return self._get_mock_calendar_events()

    def fetch_agenda_events(self) -> List[Dict]:
        """Fetch agenda events for the next 5 days from Google Calendar or return mock data"""
        # If in test mode, return mock data immediately
        if self.test_mode:
            logger.info("Test mode: Using mock agenda data")
            return self._get_mock_agenda_events()
            
        calendar_config = self.config.get('calendar', {})

        # Use real Google Calendar if configured
        if not calendar_config.get('use_mock_data', True) and self.calendar_service:
            try:
                # Handle both new multi-calendar config and legacy single calendar
                calendars = calendar_config.get('calendars', {})
                
                # Legacy fallback
                if not calendars and 'calendar_id' in calendar_config:
                    calendars = {
                        'primary': {
                            'id': calendar_config['calendar_id'],
                            'name': 'Calendar',
                            'color': '#4285F4',
                            'enabled': True
                        }
                    }
                elif not calendars and '_legacy_calendar_id' in calendar_config:
                    calendars = {
                        'primary': {
                            'id': calendar_config['_legacy_calendar_id'],
                            'name': 'Calendar',
                            'color': '#4285F4',
                            'enabled': True
                        }
                    }

                if not calendars:
                    logger.warning("No calendars configured")
                    return []

                # Initialize agenda structure for next 5 days
                agenda = []
                now = datetime.now()
                
                for i in range(5):
                    day = now + timedelta(days=i)
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

                # Fetch events from all enabled calendars and merge into agenda structure
                for calendar_key, calendar_config in calendars.items():
                    if not calendar_config.get('enabled', True):
                        continue
                        
                    calendar_id = calendar_config['id']
                    calendar_name = calendar_config.get('name', 'Calendar')
                    calendar_color = calendar_config.get('color', '#4285F4')
                    
                    try:
                        # Get raw events for proper date parsing
                        time_min = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
                        time_max = time_min + timedelta(days=5)
                        
                        events_result = self.calendar_service.service.events().list(
                            calendarId=calendar_id,
                            timeMin=time_min.isoformat() + 'Z',
                            timeMax=time_max.isoformat() + 'Z',
                            maxResults=calendar_config.get('max_events_per_calendar', 10),
                            singleEvents=True,
                            orderBy='startTime'
                        ).execute()

                        raw_events = events_result.get('items', [])
                        logger.info(f"Fetched {len(raw_events)} agenda events from calendar '{calendar_name}'")

                        # Process each raw event and place in correct agenda day
                        for event in raw_events:
                            start = event['start'].get('dateTime', event['start'].get('date'))
                            end = event['end'].get('dateTime', event['end'].get('date'))

                            # Determine event date and format
                            if 'T' in start:
                                # Timed event
                                start_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
                                end_dt = datetime.fromisoformat(end.replace('Z', '+00:00'))
                                event_date = start_dt.date()

                                event_data = {
                                    'summary': event.get('summary', 'Untitled Event'),
                                    'start': start_dt.strftime('%H:%M'),
                                    'end': end_dt.strftime('%H:%M'),
                                    'type': 'timed',
                                    'calendar_name': calendar_name,
                                    'calendar_color': calendar_color,
                                    'calendar_id': calendar_id
                                }
                            else:
                                # All-day event
                                event_date = datetime.fromisoformat(start).date()

                                event_data = {
                                    'summary': event.get('summary', 'Untitled Event'),
                                    'start': 'All Day',
                                    'end': '',
                                    'type': 'all_day',
                                    'calendar_name': calendar_name,
                                    'calendar_color': calendar_color,
                                    'calendar_id': calendar_id
                                }

                            # Find the matching agenda day
                            today = now.date()
                            days_ahead = (event_date - today).days

                            if 0 <= days_ahead < 5:
                                agenda[days_ahead]['events'].append(event_data)
                                
                    except Exception as e:
                        logger.error(f"Failed to fetch agenda events from calendar '{calendar_name}': {e}")
                        continue

                # Sort events within each day
                for day in agenda:
                    day['events'].sort(key=lambda x: x['start'] if x['start'] != 'All Day' else '00:00')

                total_events = sum(len(day['events']) for day in agenda)
                logger.info(f"Total agenda events processed: {total_events} from {len([c for c in calendars.values() if c.get('enabled', True)])} calendars")

                logger.info("Successfully created agenda from multi-calendar events")
                return agenda
                
            except Exception as e:
                logger.error(f"Failed to fetch Google Calendar agenda events: {e}")

        # Return mock agenda data for next 5 days
        logger.info("Using mock agenda data")
        return self._get_mock_agenda_events()

    def fetch_week_calendar_events(self) -> Dict[str, Dict]:
        """Fetch week calendar events from Google Calendar or return mock data"""
        calendar_config = self.config.get('calendar', {})

        # Use real Google Calendar if configured
        if not calendar_config.get('use_mock_data', True) and self.calendar_service:
            try:
                # Handle both new multi-calendar config and legacy single calendar
                calendars = calendar_config.get('calendars', {})
                
                # Legacy fallback
                if not calendars and 'calendar_id' in calendar_config:
                    calendars = {
                        'primary': {
                            'id': calendar_config['calendar_id'],
                            'name': 'Calendar',
                            'color': '#4285F4',
                            'enabled': True
                        }
                    }
                elif not calendars and '_legacy_calendar_id' in calendar_config:
                    calendars = {
                        'primary': {
                            'id': calendar_config['_legacy_calendar_id'],
                            'name': 'Calendar',
                            'color': '#4285F4',
                            'enabled': True
                        }
                    }

                # Initialize combined week structure
                combined_week_events = {}
                
                # Fetch from each enabled calendar and merge
                for cal_key, cal_info in calendars.items():
                    if not cal_info.get('enabled', True):
                        continue
                    
                    try:
                        cal_week_events = self.calendar_service.get_week_events(
                            calendar_id=cal_info['id'],
                            calendar_name=cal_info.get('name', cal_key),
                            calendar_color=cal_info.get('color', '#4285F4')
                        )
                        
                        # Merge events into combined structure
                        for date_key, day_data in cal_week_events.items():
                            if date_key not in combined_week_events:
                                combined_week_events[date_key] = day_data.copy()
                                combined_week_events[date_key]['all_day'] = []
                                combined_week_events[date_key]['timed'] = []
                            
                            combined_week_events[date_key]['all_day'].extend(day_data.get('all_day', []))
                            combined_week_events[date_key]['timed'].extend(day_data.get('timed', []))
                        
                        logger.info(f"Merged week events from calendar '{cal_info.get('name', cal_key)}'")
                    except Exception as e:
                        logger.error(f"Failed to fetch week events from calendar '{cal_info.get('name', cal_key)}': {e}")

                logger.info("Fetched week events from multiple Google Calendars")
                return combined_week_events
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
                {'summary': 'Team Standup', 'start': '09:00', 'end': '09:30', 'type': 'timed', 'calendar_name': 'Work', 'calendar_color': '#0F9D58'},
                {'summary': 'Project Review', 'start': '14:00', 'end': '15:00', 'type': 'timed', 'calendar_name': 'Work', 'calendar_color': '#0F9D58'}
            ])
            mock_week_events[today_key]['all_day'].append(
                {'summary': 'Holiday', 'type': 'all_day', 'calendar_name': 'Personal', 'calendar_color': '#4285F4'}
            )

        if tomorrow_key in mock_week_events:
            mock_week_events[tomorrow_key]['timed'].append(
                {'summary': 'Client Call', 'start': '16:00', 'end': '17:00', 'type': 'timed', 'calendar_name': 'Personal', 'calendar_color': '#4285F4'}
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

    def fetch_traffic_data(self) -> Dict:
        """Fetch traffic map and travel times data"""
        # If in test mode, return mock data immediately
        if self.test_mode:
            logger.info("Test mode: Using mock traffic data")
            return self._get_mock_traffic_data()
            
        try:
            if not self.mapbox_service:
                logger.warning("Mapbox service not available, using fallback traffic data")
                return self._get_fallback_traffic_data()
            
            traffic_config = self.config.get('traffic', {})
            destinations = traffic_config.get('destinations', [])
            
            # Get map config and travel times
            map_config = self.mapbox_service.get_map_config()
            travel_times = self.mapbox_service.get_travel_times(destinations)
            
            return {
                'map_config': map_config,
                'travel_times': travel_times,
                'service': 'mapbox'
            }
            
        except Exception as e:
            logger.error(f"Failed to fetch traffic data: {e}")
            return self._get_fallback_traffic_data()
    
    def _get_fallback_traffic_data(self) -> Dict:
        """Get fallback traffic data when Mapbox is unavailable"""
        # Use existing traffic_map config for fallback
        traffic_map = self.config.get('traffic_map', {
            'center_lat': 36.133269983139876,
            'center_lng': -80.27593704795439,
            'zoom': 12,
            'map_type': 'roadmap',
            'show_traffic': True
        })
        
        return {
            'map_config': {},  # Empty config for fallback
            'travel_times': [],
            'service': 'fallback',
            'traffic_map': traffic_map
        }

    def fetch_canvas_assignments(self) -> List[Dict]:
        """Fetch Canvas assignments"""
        if not self.canvas_service:
            logger.warning("Canvas service not available")
            return []
        
        try:
            days_ahead = self.config.get('canvas', {}).get('days_ahead', 14)
            assignments = self.canvas_service.fetch_assignments(days_ahead)
            logger.info(f"Fetched {len(assignments)} Canvas assignments")
            return assignments
        except Exception as e:
            logger.error(f"Failed to fetch Canvas assignments: {e}")
            return []

    def fetch_canvas_announcements(self) -> List[Dict]:
        """Fetch Canvas announcements"""
        if not self.canvas_service:
            logger.warning("Canvas service not available")
            return []
        
        try:
            announcements = self.canvas_service.fetch_announcements()
            logger.info(f"Fetched {len(announcements)} Canvas announcements")
            return announcements
        except Exception as e:
            logger.error(f"Failed to fetch Canvas announcements: {e}")
            return []

    def fetch_canvas_grading_queue(self) -> List[Dict]:
        """Fetch Canvas grading queue"""
        if not self.canvas_service:
            logger.warning("Canvas service not available")
            return []
        
        try:
            grading_queue = self.canvas_service.fetch_grading_queue()
            logger.info(f"Fetched {len(grading_queue)} Canvas grading queue items")
            return grading_queue
        except Exception as e:
            logger.error(f"Failed to fetch Canvas grading queue: {e}")
            return []

    def fetch_canvas_student_engagement(self) -> List[Dict]:
        """Fetch Canvas student engagement data"""
        if not self.canvas_service:
            logger.warning("Canvas service not available")
            return []
        
        try:
            student_engagement = self.canvas_service.fetch_student_engagement()
            logger.info(f"Fetched {len(student_engagement)} Canvas student engagement items")
            return student_engagement
        except Exception as e:
            logger.error(f"Failed to fetch Canvas student engagement: {e}")
            return []

    def fetch_canvas_discussion_hotspots(self) -> List[Dict]:
        """Fetch Canvas discussion hotspots"""
        if not self.canvas_service:
            logger.warning("Canvas service not available")
            return []
        
        try:
            discussion_hotspots = self.canvas_service.fetch_discussion_hotspots()
            logger.info(f"Fetched {len(discussion_hotspots)} Canvas discussion hotspots")
            return discussion_hotspots
        except Exception as e:
            logger.error(f"Failed to fetch Canvas discussion hotspots: {e}")
            return []

    def fetch_canvas_assignment_performance(self) -> List[Dict]:
        """Fetch Canvas assignment performance data"""
        if not self.canvas_service:
            logger.warning("Canvas service not available")
            return []
        
        try:
            assignment_performance = self.canvas_service.fetch_recent_assignment_performance()
            logger.info(f"Fetched {len(assignment_performance)} Canvas assignment performance items")
            return assignment_performance
        except Exception as e:
            logger.error(f"Failed to fetch Canvas assignment performance: {e}")
            return []

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
            canvas_assignments = self.fetch_canvas_assignments()
            canvas_announcements = self.fetch_canvas_announcements()
            canvas_grading_queue = self.fetch_canvas_grading_queue()
            canvas_student_engagement = self.fetch_canvas_student_engagement()
            canvas_discussion_hotspots = self.fetch_canvas_discussion_hotspots()
            canvas_assignment_performance = self.fetch_canvas_assignment_performance()

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
            
            # Traffic data (map and travel times)
            traffic_data = self.fetch_traffic_data()
            
            # Traffic map configuration
            traffic_map = self.config.get('traffic_map', {
                'center_lat': 36.133269983139876,
                'center_lng': -80.27593704795439,
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

            # Calculate week temperature range for template if forecast is available
            week_temp_min = 60
            week_temp_range = 25
            if forecast and len(forecast) > 0:
                all_temps = []
                for day in forecast:
                    if 'high' in day and 'low' in day:
                        all_temps.extend([day['high'], day['low']])
                
                if all_temps:
                    week_temp_min = min(all_temps)
                    week_temp_max = max(all_temps)
                    week_temp_range = week_temp_max - week_temp_min
                    
                    # Ensure minimum range for visual differentiation
                    if week_temp_range < 10:
                        week_temp_range = 10
                        week_temp_min = week_temp_max - 10

            # Prepare template data
            template_data = {
                'weather': weather,
                'forecast': forecast,
                'week_temp_min': week_temp_min,
                'week_temp_range': week_temp_range,
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
                'air_quality': air_quality,
                'traffic_map': traffic_data.get('traffic_map', traffic_map),
                'traffic_data': traffic_data,
                'mapbox_map_config': traffic_data.get('map_config', {}),
                'travel_times': traffic_data.get('travel_times', []),
                'google_maps_api_key': os.getenv('GOOGLE_MAPS_API_KEY'),
                'sun_position': sun_position,
                'upcoming_events': upcoming_events,
                'uv_level': uv_level,
                'month_days': month_days,
                'canvas_assignments': canvas_assignments,
                'canvas_announcements': canvas_announcements,
                'canvas_grading_queue': canvas_grading_queue,
                'canvas_student_engagement': canvas_student_engagement,
                'canvas_discussion_hotspots': canvas_discussion_hotspots,
                'canvas_assignment_performance': canvas_assignment_performance
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
    parser.add_argument('--test', action='store_true',
                       help='Use mock data instead of real API calls')
    args = parser.parse_args()

    generator = DashboardGenerator()
    
    # Set test mode if requested
    generator.test_mode = args.test

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
