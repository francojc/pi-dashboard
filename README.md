# Raspberry Pi Dashboard

A lightweight, efficient dashboard designed for Raspberry Pi B+ running in kiosk mode on a vertical display. Shows weather, RSS feeds, and calendar events with automatic updates.

## Features

- **Minimal Resource Usage**: Optimized for 512MB RAM and ARM1176 CPU
- **Server-Side Rendering**: Static HTML generation reduces browser load
- **Dark Theme**: Perfect for 24/7 display
- **Auto-Updates**: Refreshes data every 15 minutes
- **Responsive**: Optimized for vertical/portrait displays
- **Reliable**: Systemd service with automatic restarts

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   Python Script │────▶│  Static HTML     │────▶│   Chromium      │
│  (runs via cron)│     │  (generated)     │     │  (kiosk mode)   │
└─────────────────┘     └──────────────────┘     └─────────────────┘
        │                                                    │
        ▼                                                    ▼
┌─────────────────┐                              ┌─────────────────┐
│   External APIs │                              │  27" Display    │
│  - Weather      │                              │  (vertical)     │
│  - RSS Feeds    │                              └─────────────────┘
│  - Calendar     │
└─────────────────┘
```

## Requirements

### Hardware

- Raspberry Pi B+ (or newer)
- 512MB+ RAM
- 8GB+ SD Card
- Display (optimized for vertical orientation)

### Software

- Raspberry Pi OS Lite (32-bit)
- Python 3.7+
- Chromium Browser

## Quick Start

### Development (macOS/Linux)

1. Clone the repository:

```bash
git clone https://github.com/francojc/pi-dashboard.git
cd pi-dashboard
```

2. Set up Python environment:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

3. Configure API keys:
```bash
cp .env.example .env
# Edit .env with your OpenWeatherMap API key
```

4. Generate dashboard:
```bash
python src/generate_dashboard.py
```

5. View dashboard:
```bash
python -m http.server 8000 --directory output
# Open http://localhost:8000 in browser
```

### Deployment (Raspberry Pi)

1. SSH into your Raspberry Pi
2. Run the installation script:
```bash
curl -sSL https://raw.githubusercontent.com/YOUR_USERNAME/pi-dashboard/main/deployment/install.sh | bash
```

3. Configure your API keys:
```bash
nano /home/pi/pi-dashboard/.env
```

4. Reboot to start dashboard:
```bash
sudo reboot
```

## Configuration

### Weather

Edit `src/config/config.json`:

```json
{
  "weather": {
    "api_key": "YOUR_OPENWEATHER_API_KEY",
    "location": "London,UK",
    "units": "metric"
  }
}
```

Get your free API key from [OpenWeatherMap](https://openweathermap.org/api).

### RSS Feeds
Add or modify feeds in `src/config/config.json`:
```json
{
  "rss_feeds": {
    "Feed Name": "https://example.com/rss",
    "Another Feed": "https://another.com/feed.xml"
  }
}
```

### Display Settings
```json
{
  "display": {
    "refresh_interval": 900,  // seconds
    "theme": "dark"
  }
}
```

## Development

### Project Structure
```
pi-dashboard/
├── src/
│   ├── generate_dashboard.py    # Main generator script
│   ├── templates/              # Jinja2 templates
│   │   └── dashboard.html
│   ├── static/                 # CSS and static assets
│   │   └── styles.css
│   └── config/                 # Configuration files
│       └── config.json
├── deployment/                 # Pi deployment files
│   ├── dashboard-kiosk.service
│   ├── dashboard-updater.service
│   └── install.sh
├── output/                     # Generated dashboard
├── logs/                       # Application logs
└── tests/                      # Test files
```

### Testing Locally

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Run tests:
```bash
pytest tests/
```

3. Generate and serve dashboard:
```bash
python src/generate_dashboard.py
python -m http.server 8000 --directory output
```

### Customization

#### Adding New Widgets
1. Create data fetcher in `generate_dashboard.py`
2. Add widget HTML in `templates/dashboard.html`
3. Style widget in `static/styles.css`

#### Changing Layout
Edit CSS grid/flexbox in `static/styles.css`. The layout uses flexbox for vertical stacking.

## Troubleshooting

### Dashboard Not Updating
```bash
# Check timer status
sudo systemctl status dashboard-updater.timer

# View logs
journalctl -u dashboard-updater.service -f

# Run manually
cd /home/pi/pi-dashboard
./venv/bin/python src/generate_dashboard.py
```

### Display Issues
```bash
# Check kiosk service
sudo systemctl status dashboard-kiosk.service

# View Chromium logs
journalctl -u dashboard-kiosk.service -f

# Restart display
sudo systemctl restart dashboard-kiosk.service
```

### Memory Issues
The Pi B+ has limited RAM. If Chromium crashes:
1. Ensure daily reboot is enabled (4 AM by default)
2. Check swap usage: `free -h`
3. Reduce RSS feed items in config

## Performance Optimization

- **No JavaScript**: Dashboard uses only HTML/CSS
- **Minimal Cache**: Reduces SD card wear
- **Incognito Mode**: Prevents session data buildup
- **GPU Acceleration**: Uses CSS transforms for animations
- **Daily Reboot**: Clears memory leaks

## Security Considerations

- API keys stored in `.env` (not committed to git)
- Runs as non-root user (`pi`)
- No external JavaScript dependencies
- Chromium sandbox disabled (required for Pi B+)

## Contributing

1. Fork the repository
2. Create feature branch: `git checkout -b feature-name`
3. Commit changes: `git commit -am 'Add feature'`
4. Push branch: `git push origin feature-name`
5. Open Pull Request

## License

MIT License - see LICENSE file for details

## Acknowledgments

- Weather data from [OpenWeatherMap](https://openweathermap.org/)
- Inspired by MagicMirror² project
- Optimized for Raspberry Pi B+ constraints
