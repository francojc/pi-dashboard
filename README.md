# Pi Dashboard Web Service

A modern dashboard web service designed to run in Docker and be accessed by Raspberry Pi devices in kiosk mode. Features a card-based design with weather, calendar, local information, and news feeds with automatic updates.

## Features

- **Web Service Architecture**: Runs in Docker on powerful hardware, accessed by Pi via network
- **Modern Card-Based Design**: Glassmorphism effects with performance optimizations
- **Server-Side Rendering**: Static HTML generation reduces client load
- **Enhanced Local Information**: Air quality, UV index, sun position, traffic patterns
- **Auto-Updates**: Refreshes data every 15 minutes
- **Real Weather Data**: Current conditions, 5-day forecast, and air quality from OpenWeatherMap
- **Smart Calendar**: Complete month view with adjacent month days
- **RSS Feed Support**: Dual news and events tickers with smooth animations
- **Responsive**: Optimized for vertical/portrait displays
- **Multiple Pi Support**: Single dashboard service can serve multiple displays
- **Secure Remote Access**: Tailscale integration for secure remote viewing

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   Docker Host   │────▶│   Web Service    │────▶│  Raspberry Pi   │
│  (Server/NAS)   │     │  (Port 8080)     │     │  (Kiosk Mode)   │
└─────────────────┘     └──────────────────┘     └─────────────────┘
        │                        │                        │
        ▼                        ▼                        ▼
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   External APIs │     │  Static HTML     │     │   Midori/       │
│  - Weather      │     │  (Auto-refresh)  │     │   Chromium      │
│  - RSS Feeds    │     │                  │     │   (Fullscreen)  │
│  - Calendar     │     │                  │     │                 │
└─────────────────┘     └──────────────────┘     └─────────────────┘
                                                          │
                         Optional: Tailscale             ▼
                        ┌──────────────────┐     ┌─────────────────┐
                        │    TSDProxy      │     │   Display       │
                        │ (Reverse Proxy)  │     │  (Vertical)     │
                        └──────────────────┘     └─────────────────┘
```

## Requirements

### Docker Host (Server/NAS/Desktop)

- **Hardware**: Any x86/ARM64 device with Docker support
- **Software**: Docker and Docker Compose
- **Network**: Internet access for API calls
- **Optional**: Tailscale account for secure remote access

### Raspberry Pi (Display Client)

- **Hardware**: Raspberry Pi 2B+ or newer, 8GB+ SD Card, Display
- **Software**: Raspberry Pi OS Lite, X11, Midori or Chromium
- **Network**: WiFi or Ethernet access to Docker host

## Quick Start

## Step 1: Deploy Dashboard Service

Deploy the dashboard web service on a powerful device (server, NAS, desktop):

```bash
# Clone repository
git clone https://github.com/francojc/pi-dashboard-docker.git
cd pi-dashboard-docker

# Set up environment
cp .env.example .env
# Edit .env with your OpenWeatherMap API key

# Deploy with Docker
docker compose up -d

# Access at http://localhost:8080
```

**Service Management:**
```bash
# View logs
docker compose logs -f

# Restart services
docker compose restart

# Stop services
docker compose down

# Update and rebuild
git pull && docker compose up -d --build
```

### Remote Access with Tailscale (Recommended)

For secure access across networks, set up Tailscale:

1. **Install Tailscale on Docker host:**
   ```bash
   # Follow instructions at https://tailscale.com/download
   curl -fsSL https://tailscale.com/install.sh | sh
   sudo tailscale up
   ```

2. **Configure TSDProxy for easy access:**
   ```bash
   # Install TSDProxy (Tailscale reverse proxy)
   go install github.com/almeidapaulopt/tsdproxy@latest
   
   # Create config for dashboard
   tsdproxy --from dashboard --to localhost:8080
   ```

3. **Access dashboard at:** `https://dashboard.your-tailnet.ts.net`

### Google Calendar (Optional)

To enable Google Calendar integration:

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create OAuth 2.0 credentials (Desktop application)
3. Add `http://localhost:8081` as authorized redirect URI
4. Update `.env` with your credentials
5. Run `python src/generate_dashboard.py` once to authenticate

Then specify your calendar ID(s) in `src/config/config.json`:

```json
{
  "calendar": {
    "ids": ["calendar_id_1", "calendar_id_2"],
    "timezone": "Europe/London",
    "max_events": 5
  }
}
```

## Step 2: Configure Raspberry Pi Kiosk

Set up your Raspberry Pi as a kiosk display client:

### 1. Install Raspberry Pi OS

1. Download [Raspberry Pi OS Lite](https://www.raspberrypi.org/software/operating-systems/) (32-bit)
2. Flash to SD card using [Raspberry Pi Imager](https://www.raspberrypi.org/software/)
3. Enable SSH by creating empty `ssh` file in boot partition
4. Boot Pi and SSH in: `ssh pi@raspberrypi.local`

### 2. Basic System Setup

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install required packages for kiosk mode
sudo apt install -y \
    xserver-xorg-video-fbdev \
    xserver-xorg \
    xinit \
    x11-xserver-utils \
    matchbox-window-manager \
    midori \
    unclutter

# Configure auto-login (optional)
sudo raspi-config
# System Options → Boot / Auto Login → Console Autologin
```

### 3. Configure Kiosk Mode

Replace `DASHBOARD_URL` with your dashboard service URL:

**For local network access:**
```bash
DASHBOARD_URL="http://192.168.1.100:8080"  # Replace with your Docker host IP
```

**For Tailscale access:**
```bash
DASHBOARD_URL="https://dashboard.your-tailnet.ts.net"
```

**Create kiosk startup script:**

```bash
cat > /home/pi/kiosk.sh << 'EOF'
#!/bin/bash

# Dashboard URL - Update this with your service URL
DASHBOARD_URL="http://192.168.1.100:8080"

# Disable screen blanking and power management
xset -dpms
xset s off
xset s noblank

# Hide mouse cursor
unclutter -idle 0.5 -root &

# Start window manager
matchbox-window-manager -use_titlebar no &

# Wait a moment for WM to start
sleep 2

# Start browser in kiosk mode
midori -e Fullscreen -a "$DASHBOARD_URL"
EOF

chmod +x /home/pi/kiosk.sh
```

### 4. Auto-Start Kiosk on Boot

```bash
# Create .xinitrc to start kiosk
echo 'exec /home/pi/kiosk.sh' > /home/pi/.xinitrc

# Auto-start X11 on login
cat >> /home/pi/.bash_profile << 'EOF'
if [ -z "$DISPLAY" ] && [ "$XDG_VTNR" = 1 ]; then
    startx
fi
EOF
```

### 5. Display Configuration (Optional)

**For vertical displays, configure rotation:**

```bash
# Add to /boot/firmware/config.txt
echo 'display_rotate=1' | sudo tee -a /boot/firmware/config.txt
echo 'gpu_mem=64' | sudo tee -a /boot/firmware/config.txt
```

**Alternative browser options:**

```bash
# For Chromium instead of Midori (more resource intensive, but not available for older Pi models):
sudo apt install -y chromium-browser

# Update kiosk.sh to use Chromium:
# chromium-browser --kiosk --noerrdialogs --disable-infobars --incognito "$DASHBOARD_URL"
```

### 6. System Optimizations

**Resource optimization for older Pi models:**

```bash
# Disable unnecessary services
sudo systemctl disable bluetooth
sudo systemctl disable wifi-powersave@wlan0.service

# Add to /boot/firmware/config.txt for better performance
echo 'disable_overscan=1' | sudo tee -a /boot/firmware/config.txt
echo 'dtparam=audio=off' | sudo tee -a /boot/firmware/config.txt

# Set up daily reboot at 4 AM (optional)
echo '0 4 * * * /sbin/reboot' | crontab -
```

**Test the setup:**

```bash
# Reboot to test auto-start
sudo reboot

# Or start manually for testing
startx
```

## Development & Testing

For local development and testing:

```bash
# Clone repository
git clone https://github.com/francojc/pi-dashboard-docker.git
cd pi-dashboard-docker

# Set up Python environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure API keys
cp .env.example .env
# Edit .env with your OpenWeatherMap API key

# Generate dashboard once
python src/generate_dashboard.py

# View generated output
python -m http.server 8000 --directory output
# Open http://localhost:8000 in browser
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
    "Another Feed": "https://another.com/feed.xml",
    "Reddit ClaudeAI": "https://www.reddit.com/r/ClaudeAI/.rss"
  }
}
```

**Reddit RSS Format:**

- Basic: `https://www.reddit.com/r/SUBREDDIT/.rss`
- Hot posts: `https://www.reddit.com/r/SUBREDDIT/hot/.rss`
- New posts: `https://www.reddit.com/r/SUBREDDIT/new/.rss`
- Top posts: `https://www.reddit.com/r/SUBREDDIT/top/.rss`

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
│   └── config/                 # Configuration files
│       └── config.json
├── deployment/                 # Pi deployment files
│   ├── dashboard-kiosk.service
│   ├── dashboard-updater.service
│   └── install.sh
├── output/                     # Generated dashboard
│    └── index.html
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

### Docker Service Issues

```bash
# Check service status
docker compose ps

# View logs
docker compose logs -f

# Restart services
docker compose restart

# Check dashboard accessibility
curl -I http://localhost:8080
```

### Pi Kiosk Issues

```bash
# Check X11 status
ps aux | grep X

# Restart kiosk manually
sudo pkill X
startx

# View system logs
journalctl -f

# Test browser manually
DISPLAY=:0 midori -e Fullscreen -a http://your-dashboard-url:8080
```

### Network Connectivity

```bash
# Test dashboard access from Pi
curl -I http://your-docker-host:8080

# For Tailscale issues
sudo tailscale status
sudo tailscale ping your-docker-host

# Check DNS resolution
nslookup dashboard.your-tailnet.ts.net
```

### Performance Issues

For older Pi models experiencing slow performance:

1. Use Midori instead of Chromium
2. Increase GPU memory: `gpu_mem=128` in `/boot/firmware/config.txt`
3. Enable daily reboot: `0 4 * * * /sbin/reboot` in crontab
4. Disable unnecessary services

## Performance Optimization

### Docker Service
- **Server-side rendering**: Static HTML generation reduces client load
- **Efficient caching**: Docker volumes for persistent data
- **Resource management**: Automatic container restart on failure

### Pi Kiosk Client
- **Lightweight browser**: Midori recommended for older Pi models
- **No JavaScript dependencies**: Dashboard uses only HTML/CSS
- **Minimal cache**: Incognito/private browsing prevents buildup
- **GPU acceleration**: CSS transforms for smooth animations
- **Memory management**: Daily reboot clears potential leaks

## Security Considerations

### Docker Service
- API keys stored in environment variables (not in images)
- Containers run as non-root users
- No external JavaScript dependencies
- OAuth tokens stored as mounted files (not in containers)

### Network Security
- **Tailscale recommended**: End-to-end encrypted access
- **TSDProxy**: HTTPS termination and domain routing
- **Local network**: Standard HTTP for internal access
- **Pi client**: Read-only access to dashboard service

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
- [Tailscale](https://tailscale.com/) for secure networking
- [TSDProxy](https://github.com/almeidapaulopt/tsdproxy) for reverse proxy
- Designed for low-resource Pi devices as display clients
