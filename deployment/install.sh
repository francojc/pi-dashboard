#!/bin/bash
# Dashboard Installation Script for Raspberry Pi

set -e

# Default values
USERNAME="pi"
REPO_USER="YOUR_USERNAME"

# Parse command line arguments
while getopts "u:g:h" opt; do
    case $opt in
        u)
            USERNAME="$OPTARG"
            ;;
        g)
            REPO_USER="$OPTARG"
            ;;
        h)
            echo "Usage: $0 [-u username] [-g github_user]"
            echo "  -u username    System username (default: pi)"
            echo "  -g github_user GitHub repository username (default: YOUR_USERNAME)"
            echo "  -h             Show this help"
            exit 0
            ;;
        \?)
            echo "Invalid option: -$OPTARG" >&2
            echo "Use -h for help"
            exit 1
            ;;
    esac
done

echo "=== Raspberry Pi Dashboard Installer ==="
echo "Installing for user: $USERNAME"
echo "GitHub repository: https://github.com/$REPO_USER/pi-dashboard.git"
echo

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
sudo apt-get update
sudo apt-get upgrade -y

# Install required packages
echo "Installing required packages..."
sudo apt-get install -y \
    xserver-xorg \
    xinit \
    chromium-browser \
    unclutter \
    python3-pip \
    python3-venv \
    git

# Create directory and clone repository
echo "Setting up dashboard directory..."
cd /home/$USERNAME

if [ -d "pi-dashboard" ]; then
    echo "Dashboard directory already exists. Pulling latest changes..."
    cd pi-dashboard
    git pull
else
    echo "Cloning dashboard repository..."
    git clone https://github.com/$REPO_USER/pi-dashboard.git
    cd pi-dashboard
fi

# Set up Python virtual environment
echo "Setting up Python virtual environment..."
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Copy configuration
echo "Setting up configuration..."
if [ ! -f .env ]; then
    cp .env.example .env
    echo "Please edit .env file with your API keys"
fi

# Create necessary directories
mkdir -p output logs

# Configure X11 for kiosk mode
echo "Configuring X11 for kiosk mode..."
cat > /home/$USERNAME/.xinitrc << EOF
#!/bin/bash
xset -dpms      # Disable DPMS (Energy Star)
xset s off      # Disable screen saver
xset s noblank  # Don't blank the video device
unclutter -idle 0.5 -root &  # Hide cursor
chromium-browser --noerrdialogs --disable-infobars --kiosk --incognito file:///home/$USERNAME/pi-dashboard/output/index.html
EOF

chmod +x /home/$USERNAME/.xinitrc

# Configure auto-start X11 on boot
echo "Configuring auto-start X11..."
if ! grep -q "startx" /home/$USERNAME/.bash_profile 2>/dev/null; then
    cat >> /home/$USERNAME/.bash_profile << EOF

# Auto-start X11 for dashboard
if [ -z "\$DISPLAY" ] && [ "\$XDG_VTNR" = 1 ]; then
  startx
fi
EOF
fi

# Configure display rotation for vertical orientation
echo "Configuring display for vertical orientation..."
if ! grep -q "display_rotate=1" /boot/firmware/config.txt; then
    echo "# Display rotation (90° for vertical)" | sudo tee -a /boot/firmware/config.txt
    echo "display_rotate=1" | sudo tee -a /boot/firmware/config.txt
    echo "gpu_mem=64" | sudo tee -a /boot/firmware/config.txt
fi

# Run initial dashboard generation
echo "Generating initial dashboard..."
python src/generate_dashboard.py

# Install systemd services
echo "Installing systemd services..."
sudo cp deployment/dashboard-kiosk.service /etc/systemd/system/
sudo cp deployment/dashboard-updater.service /etc/systemd/system/
sudo cp deployment/dashboard-updater.timer /etc/systemd/system/

# Reload systemd and enable services
sudo systemctl daemon-reload
sudo systemctl enable dashboard-kiosk.service
sudo systemctl enable dashboard-updater.timer

# Configure auto-login (optional)
read -p "Enable auto-login for $USERNAME user? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    sudo mkdir -p /etc/systemd/system/getty@tty1.service.d/
    sudo tee /etc/systemd/system/getty@tty1.service.d/autologin.conf > /dev/null <<EOF
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin $USERNAME --noclear %I \$TERM
EOF
fi

# Set up daily reboot cron job
echo "Setting up daily reboot..."
(crontab -l 2>/dev/null; echo "0 4 * * * /sbin/reboot") | crontab -

echo
echo "=== Installation Complete ==="
echo
echo "The following configurations have been applied:"
echo "✓ X11 kiosk mode configured"
echo "✓ Auto-start X11 on boot configured"
echo "✓ Display rotation set to vertical (90°)"
echo "✓ GPU memory split set to 64MB"
echo "✓ Systemd services installed and enabled"
echo
echo "Next steps:"
echo "1. Edit /home/$USERNAME/pi-dashboard/.env with your API keys"
echo "2. Edit /home/$USERNAME/pi-dashboard/src/config/config.json for customization"
echo "3. Reboot the Pi to start the dashboard: sudo reboot"
echo
echo "Additional manual configurations (if needed):"
echo "• Run 'sudo raspi-config' to configure boot options and SSH"
echo "• Disable unused services (WiFi, Bluetooth) if using Ethernet"
echo
echo "To start services manually:"
echo "  sudo systemctl start dashboard-updater.timer"
echo "  sudo systemctl start dashboard-kiosk.service"