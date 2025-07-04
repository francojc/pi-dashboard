#!/usr/bin/env python3
"""Test dashboard generator without external dependencies"""

import json
from datetime import datetime
from pathlib import Path
from jinja2 import Environment, FileSystemLoader

# Create a simple test
def test_dashboard():
    # Mock data
    weather = {
        'temp': 22,
        'feels_like': 20,
        'description': 'Partly Cloudy',
        'icon': '02d',
        'humidity': 65,
        'wind_speed': 12.5
    }
    
    articles = [
        {'source': 'BBC News', 'title': 'Test Article 1', 'summary': 'This is a test article...'},
        {'source': 'Hacker News', 'title': 'Test Article 2', 'summary': 'Another test article...'},
        {'source': 'Reuters', 'title': 'Test Article 3', 'summary': 'Yet another test article...'}
    ]
    
    events = [
        {'summary': 'Team Standup', 'start': '09:00', 'end': '09:30'},
        {'summary': 'Project Review', 'start': '14:00', 'end': '15:00'},
        {'summary': 'Client Call', 'start': '16:00', 'end': '17:00'}
    ]
    
    # Template data
    template_data = {
        'weather': weather,
        'articles': articles,
        'events': events,
        'last_updated': datetime.now().strftime('%H:%M:%S'),
        'config': {'refresh_interval': 900}
    }
    
    # Render template
    env = Environment(loader=FileSystemLoader('src/templates'))
    template = env.get_template('dashboard.html')
    html_content = template.render(template_data)
    
    # Write output
    output_dir = Path('output')
    output_dir.mkdir(exist_ok=True)
    
    output_path = output_dir / 'index.html'
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    # Also copy CSS
    css_source = Path('src/static/styles.css')
    css_dest = output_dir / 'static'
    css_dest.mkdir(exist_ok=True)
    
    with open(css_source, 'r') as src, open(css_dest / 'styles.css', 'w') as dst:
        dst.write(src.read())
    
    print(f"Dashboard generated successfully at: {output_path}")
    return True

if __name__ == "__main__":
    test_dashboard()