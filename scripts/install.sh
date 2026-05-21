#!/bin/bash
# NOCTYRA360™ Production Installer
# Run once on a fresh Ubuntu 22.04 server
# ONE COMMAND: bash install.sh

set -e
echo ""
echo "=================================================="
echo "  NOCTYRA360™ Production Installer"
echo "  Connect Now USA LLC"
echo "=================================================="
echo ""

# Update system
echo "[1/8] Updating system..."
apt-get update -qq && apt-get upgrade -y -qq

# Install Python and dependencies
echo "[2/8] Installing Python 3.11..."
apt-get install -y -qq python3.11 python3.11-venv python3-pip nginx git curl

# Create app user (never run as root)
echo "[3/8] Creating noctyra system user..."
id -u noctyra &>/dev/null || useradd -m -s /bin/bash noctyra

# Create directories
echo "[4/8] Creating application directories..."
mkdir -p /opt/noctyra360/{app,uploads,reports,config,logs}
chown -R noctyra:noctyra /opt/noctyra360

# Copy application files
echo "[5/8] Installing application..."
cp -r . /opt/noctyra360/app/
chown -R noctyra:noctyra /opt/noctyra360/app

# Python virtual environment
echo "[6/8] Setting up Python environment..."
cd /opt/noctyra360/app
python3.11 -m venv venv
source venv/bin/activate
pip install --quiet \
    fastapi uvicorn[standard] \
    pandas numpy chardet \
    aiofiles python-multipart \
    reportlab openpyxl \
    celery redis psycopg2-binary

# Systemd service
echo "[7/8] Installing system service..."
cat > /etc/systemd/system/noctyra360.service << 'SERVICE'
[Unit]
Description=NOCTYRA360 Production Platform
After=network.target

[Service]
Type=simple
User=noctyra
WorkingDirectory=/opt/noctyra360/app
ExecStart=/opt/noctyra360/app/venv/bin/uvicorn api.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5
StandardOutput=append:/opt/noctyra360/logs/app.log
StandardError=append:/opt/noctyra360/logs/error.log

[Install]
WantedBy=multi-user.target
SERVICE

systemctl daemon-reload
systemctl enable noctyra360
systemctl start noctyra360

# Nginx reverse proxy
echo "[8/8] Configuring Nginx..."
cat > /etc/nginx/sites-available/noctyra360 << 'NGINX'
server {
    listen 80;
    server_name _;
    client_max_body_size 20G;

    location /api/ {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 3600s;
    }

    location / {
        root /opt/noctyra360/app/frontend;
        index index.html;
        try_files $uri $uri/ /index.html;
    }
}
NGINX

ln -sf /etc/nginx/sites-available/noctyra360 /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

echo ""
echo "=================================================="
echo "  NOCTYRA360™ INSTALLED SUCCESSFULLY"
echo ""
echo "  API:       http://YOUR_SERVER_IP/api/"
echo "  Health:    http://YOUR_SERVER_IP/"
echo "  Logs:      /opt/noctyra360/logs/"
echo ""
echo "  Status:    systemctl status noctyra360"
echo "  Restart:   systemctl restart noctyra360"
echo "=================================================="
