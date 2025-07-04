#!/usr/bin/env python3
"""
Test OAuth flow in isolation
"""
import os
from dotenv import load_dotenv
from google_auth_oauthlib.flow import InstalledAppFlow

# Load environment variables
load_dotenv()

SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']

def test_oauth():
    client_id = os.getenv('GOOGLE_CALENDAR_CLIENT_ID')
    client_secret = os.getenv('GOOGLE_CALENDAR_CLIENT_SECRET')
    
    print(f"Client ID: {client_id[:20]}...{client_id[-10:] if client_id else 'None'}")
    print(f"Client Secret: {'*' * len(client_secret) if client_secret else 'None'}")
    
    if not client_id or not client_secret:
        print("ERROR: Missing credentials")
        return
    
    # Create client configuration
    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "redirect_uris": ["http://127.0.0.1:8081"]
        }
    }
    
    print("\nStarting OAuth flow...")
    print("Expected redirect URI: http://localhost:8081")
    print("Please make sure this URI is registered in Google Cloud Console")
    
    try:
        flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
        credentials = flow.run_local_server(port=8080, open_browser=True)
        
        print("\n✅ OAuth flow completed successfully!")
        print(f"Token: {credentials.token[:20]}...")
        
        # Save token for main app
        with open('token.json', 'w') as token:
            token.write(credentials.to_json())
        print("Token saved to token.json")
        
    except Exception as e:
        print(f"\n❌ OAuth flow failed: {e}")
        print(f"Error type: {type(e).__name__}")

if __name__ == "__main__":
    test_oauth()