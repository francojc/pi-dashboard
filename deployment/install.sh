#!/bin/bash
# Raspberry Pi Kiosk Setup Script for Pi Dashboard
# Configures a Raspberry Pi as a kiosk display client for the dashboard web service

set -e

# Default values
USERNAME="pi"
DASHBOARD_URL=""

# Parse command line arguments
while getopts "u:d:h" opt; do
    case $opt in
        u)
            USERNAME="$OPTARG"
            ;;
        d)
            DASHBOARD_URL="$OPTARG"
            ;;
        h)
            echo "Usage: $0 [-u username] [-d dashboard_url]"
            echo "  -u username      System username (default: pi)"
            echo "  -d dashboard_url Dashboard service URL (e.g., http://192.168.1.100:8080)"
            echo "  -h               Show this help"
            echo ""
            echo "Example:"
            echo "  $0 -d http://192.168.1.100:8080"
            echo "  $0 -d https://dashboard.your-tailnet.ts.net"
            exit 0
            ;;
        \?)
            echo "Invalid option: -$OPTARG" >&2
            echo "Use -h for help"
            exit 1
            ;;
    esac
done

echo "=== Raspberry Pi Dashboard Kiosk Installer ==="
echo "Setting up kiosk for user: $USERNAME"

# Prompt for dashboard URL if not provided
if [ -z "$DASHBOARD_URL" ]; then
    echo ""
    echo "Enter the dashboard service URL:"
    echo "Examples:"
    echo "  http://192.168.1.100:8080 (local network)"
    echo "  https://dashboard.your-tailnet.ts.net (Tailscale)"
    read -p "Dashboard URL: " DASHBOARD_URL
    
    if [ -z "$DASHBOARD_URL" ]; then
        echo "Error: Dashboard URL is required"
        exit 1
    fi
fi

echo "Dashboard URL: $DASHBOARD_URL"
echo ""

# Check if running on Raspberry Pi
if [ ! -f /proc/device-tree/model ]; then
    echo "Warning: This doesn't appear to be a Raspberry Pi."
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Update system
echo "Updating system packages..."
sudo apt update && sudo apt upgrade -y

# Install required packages for kiosk mode
echo "Installing required packages..."
sudo apt install -y \
    xserver-xorg-video-fbdev \
    xserver-xorg \
    xinit \
    x11-xserver-utils \
    matchbox-window-manager \
    midori \
    unclutter

# Create kiosk startup script
echo "Creating kiosk startup script..."
cat > /home/$USERNAME/kiosk.sh << 'EOF'
#!/bin/bash

# Dashboard URL - Set during installation
DASHBOARD_URL="PLACEHOLDER_URL"

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

# Replace placeholder with actual URL
sed -i "s|PLACEHOLDER_URL|$DASHBOARD_URL|g" /home/$USERNAME/kiosk.sh
chmod +x /home/$USERNAME/kiosk.sh

# Create .xinitrc to start kiosk
echo "Configuring X11 startup..."
echo 'exec /home/'$USERNAME'/kiosk.sh' > /home/$USERNAME/.xinitrc

# Auto-start X11 on login
echo "Configuring auto-start X11..."
if ! grep -q "startx" /home/$USERNAME/.bash_profile 2>/dev/null; then
    cat >> /home/$USERNAME/.bash_profile << 'EOF'
if [ -z "$DISPLAY" ] && [ "$XDG_VTNR" = 1 ]; then
    startx
fi
EOF
fi

# Configure auto-login (optional)
read -p "Enable auto-login for $USERNAME user? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "Configuring auto-login..."
    sudo raspi-config nonint do_boot_behaviour B2
fi

# Configure display rotation for vertical displays (optional)
read -p "Configure display for vertical orientation? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "Configuring display rotation..."
    if ! grep -q "display_rotate=1" /boot/firmware/config.txt 2>/dev/null; then
        echo 'display_rotate=1' | sudo tee -a /boot/firmware/config.txt
        echo 'gpu_mem=64' | sudo tee -a /boot/firmware/config.txt
    fi
fi

# System optimizations
echo "Applying system optimizations..."

# Disable unnecessary services
sudo systemctl disable bluetooth 2>/dev/null || true
sudo systemctl disable wifi-powersave@wlan0.service 2>/dev/null || true

# Add performance optimizations to config.txt
if ! grep -q "disable_overscan=1" /boot/firmware/config.txt 2>/dev/null; then
    echo 'disable_overscan=1' | sudo tee -a /boot/firmware/config.txt
fi
if ! grep -q "dtparam=audio=off" /boot/firmware/config.txt 2>/dev/null; then
    echo 'dtparam=audio=off' | sudo tee -a /boot/firmware/config.txt
fi

# Set up daily reboot at 4 AM (optional)
read -p "Set up daily reboot at 4 AM? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "Setting up daily reboot..."
    (crontab -l 2>/dev/null | grep -v "/sbin/reboot"; echo '0 4 * * * /sbin/reboot') | crontab -
fi

echo ""
echo "=== Installation Complete ==="
echo ""
echo "Kiosk configuration:"
echo "✓ X11 and required packages installed"
echo "✓ Kiosk startup script created: /home/$USERNAME/kiosk.sh"
echo "✓ Dashboard URL: $DASHBOARD_URL"
echo "✓ Auto-start X11 configured"
echo "✓ System optimizations applied"
echo ""
echo "Next steps:"
echo "1. Test the setup: sudo reboot"
echo "2. The dashboard should start automatically after reboot"
echo ""
echo "Manual testing:"
echo "  startx                    # Start kiosk manually"
echo "  /home/$USERNAME/kiosk.sh  # Test kiosk script directly"
echo ""
echo "Troubleshooting:"
echo "  journalctl -f            # View system logs"
echo "  ps aux | grep X          # Check X11 status"
echo "  curl -I $DASHBOARD_URL   # Test dashboard connectivity"