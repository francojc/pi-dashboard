# Raspberry Pi Dashboard

A lightweight, efficient dashboard designed for Raspberry Pi B+ running in kiosk mode on a vertical display. Features a modern card-based design with weather, calendar, local information, and news feeds with automatic updates.

## Features

- **Modern Card-Based Design**: Glassmorphism effects with performance optimizations
- **Minimal Resource Usage**: Optimized for 512MB RAM and ARM1176 CPU
- **Server-Side Rendering**: Static HTML generation reduces browser load
- **Enhanced Local Information**: Air quality, UV index, sun position, traffic patterns
- **Auto-Updates**: Refreshes data every 15 minutes
- **Real Weather Data**: Current conditions, 5-day forecast, and air quality from OpenWeatherMap
- **Smart Calendar**: Complete month view with adjacent month days
- **RSS Feed Support**: Dual news and events tickers with smooth animations
- **Responsive**: Optimized for vertical/portrait displays
- **Reliable**: Systemd service with automatic restarts and fallback data

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

### Basic Raspberry Pi Setup

The installation script automatically configures most settings for kiosk mode, but you should understand what it does to your system. Only basic OS setup is required first:

#### 1. Install Raspberry Pi OS Lite

1. Download [Raspberry Pi OS Lite](https://www.raspberrypi.org/software/operating-systems/) (32-bit)
2. Flash to SD card using [Raspberry Pi Imager](https://www.raspberrypi.org/software/)
3. Enable SSH by creating empty `ssh` file in boot partition
4. Boot Pi and SSH in: `ssh pi@raspberrypi.local` (default user is `pi` and password is `raspberry`)

#### 2. Basic System Configuration

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Configure Pi settings (optional - for boot options, SSH, filesystem)
sudo raspi-config
```

**Optional `raspi-config` settings:**

- **System Options** → **Boot / Auto Login** → **Console Autologin**
- **Interface Options** → **SSH** → **Enable** 
- **Advanced Options** → **Expand Filesystem**

> **Note:** The installation script will automatically configure X11 kiosk mode, display rotation, GPU memory, and auto-start settings.

### Development (macOS/Linux)

1. Clone the repository:

*Note: you will need Git installed. If you don't have it, install it with `sudo apt install git -y` on your Raspberry Pi.*

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

**Prerequisites:** Complete the [Basic Raspberry Pi Setup](#basic-raspberry-pi-setup) section above first.

1. SSH into your Raspberry Pi
2. Download and run the installation script:

```bash
# Download the script
wget https://raw.githubusercontent.com/YOUR_USERNAME/pi-dashboard/main/deployment/install.sh
chmod +x install.sh

# Run with default settings (pi user, YOUR_USERNAME repo)
./install.sh

# Or specify custom user and GitHub username
./install.sh -u myuser -g githubuser

# See all options
./install.sh -h
```

**Installation Script Options:**

- `-u username` - System username (default: pi)
- `-g github_user` - GitHub repository username (default: YOUR_USERNAME)  
- `-h` - Show help

**What the installation script configures automatically:**

- ✅ **X11 kiosk mode**: Creates `/home/USERNAME/.xinitrc` with Chromium fullscreen settings
- ✅ **Auto-start X11**: Adds startup commands to `/home/USERNAME/.bash_profile`
- ✅ **Display rotation**: Adds `display_rotate=1` and `gpu_mem=64` to `/boot/firmware/config.txt`
- ✅ **Dashboard services**: Installs systemd services for automatic updates
- ✅ **Daily reboot**: Adds cron job for 4 AM daily restart

**Files modified by the installer:**

```
/home/USERNAME/.xinitrc          # X11 startup script (created)
/home/USERNAME/.bash_profile     # Auto-start X11 (appended)
/boot/config.txt        # Display settings (appended)
/etc/systemd/system/             # Dashboard services (copied)
/var/spool/cron/crontabs/        # Daily reboot cron (added)
```

3. Configure your API keys (replace `pi` with your username if different):

```bash
nano /home/pi/pi-dashboard/.env
```

4. Reboot to start dashboard:

```bash
sudo reboot
```

#### Manual Configuration Details

If you prefer to configure manually or want to understand what the installer does, here are the equivalent manual steps:

<details>
<summary>🔧 Click to see manual configuration steps</summary>

**1. Create X11 startup script:**

```bash
nano /home/pi/.xinitrc
```

Add:

```bash
#!/bin/bash
xset -dpms
xset s off
xset s noblank
unclutter -idle 0.5 -root &
chromium-browser --noerrdialogs --disable-infobars --kiosk --incognito file:///home/pi/pi-dashboard/output/index.html
```
```bash
chmod +x /home/pi/.xinitrc
```

**2. Configure auto-start X11:**

```bash
nano /home/pi/.bash_profile
```
Add:
```bash
if [ -z "$DISPLAY" ] && [ "$XDG_VTNR" = 1 ]; then
  startx
fi
```

**3. Configure display rotation:**

```bash
sudo nano /boot/firmware/config.txt
```
Add:
```ini
display_rotate=1
gpu_mem=64
```

**4. Set up daily reboot:**
```bash
crontab -e
```
Add:
```
0 4 * * * /sbin/reboot
```

</details>

#### Optional System Optimizations

Additional optimizations you can apply manually:

```bash
# Disable Bluetooth and WiFi if using Ethernet only
sudo systemctl disable bluetooth hciuart
echo 'dtoverlay=disable-wifi' | sudo tee -a /boot/firmware/config.txt
echo 'dtoverlay=disable-bt' | sudo tee -a /boot/firmware/config.txt

# Disable other services to save resources
sudo systemctl disable triggerhappy
sudo systemctl disable dphys-swapfile  # If you have enough RAM
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

# Run manually (replace pi with your username if different)
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
