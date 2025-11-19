# DigitalOcean Deployment Guide

## Overview

This guide shows how to deploy both the main Melissa Response website and the geocoder app on a single DigitalOcean droplet.

**Architecture:**
- `melissa-response.org` → Nginx → Main app (port 3000 or your main app port)
- `geocode.melissa-response.org` → Nginx → Geocoder app (port 8000)

Both apps run as systemd services behind nginx reverse proxy with SSL.

**Recommended Droplet Size:**
- **$12/month** (2GB RAM, 1 vCPU, 50GB SSD) - Comfortable for both apps
- **$18/month** (2GB RAM, 2 vCPU, 60GB SSD) - Better performance if traffic increases

## Initial Server Setup

```bash
# SSH into your droplet
ssh root@YOUR_DROPLET_IP

# Update system
apt update && apt upgrade -y

# Install required packages
apt install -y python3 python3-pip python3-venv nginx certbot python3-certbot-nginx git

# Create app user
adduser --disabled-password --gecos "" geocoder
usermod -aG sudo geocoder

# Switch to app user
su - geocoder
```

## Deploy Both Applications

### Deploy Main Website

```bash
# Deploy your main Melissa Response app
mkdir -p ~/apps
cd ~/apps

# Clone or upload your main website
# This depends on your main app's tech stack (Node.js, Python, etc.)
# Example for a typical web app:
git clone https://github.com/your-org/melissa-response.git main-site
cd main-site

# Install dependencies (adjust based on your tech stack)
# For Node.js:
# npm install
# For Python:
# python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt

# Configure environment variables
# Create .env file with your main app's settings

# Test the app runs on port 3000 (or whatever port your main app uses)
```

### Deploy Geocoder Application

```bash
# Return to apps directory
cd ~/apps

# If using git (recommended)
git clone https://github.com/joshuaberetta/jamaica-geocoder.git geocoder
cd geocoder

# OR upload files directly using scp from your local machine:
# scp -r /Users/josh/Desktop/melissa\ response/forms/scripts/geocode/* geocoder@YOUR_DROPLET_IP:~/apps/geocoder/

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Create .env file
cat > .env << EOF
SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
LOGIN_USERNAME=your_username
LOGIN_PASSWORD=your_secure_password
BOUNDARIES_FILE=odpem.geojson
PORT=8000
EOF

# Test the app
python web_app.py
# Press Ctrl+C to stop
```

## Set up Systemd Services

### Main Website Service

```bash
# Exit back to root user
exit

# Create systemd service for main website
# Adjust this based on your main app's tech stack
cat > /etc/systemd/system/melissa-main.service << 'EOF'
[Unit]
Description=Melissa Response Main Website
After=network.target

[Service]
Type=exec
User=geocoder
Group=geocoder
WorkingDirectory=/home/geocoder/apps/main-site
# Adjust Environment and ExecStart based on your app
# For Node.js:
# Environment="NODE_ENV=production"
# ExecStart=/usr/bin/node server.js
# For Python/Flask:
# Environment="PATH=/home/geocoder/apps/main-site/venv/bin"
# ExecStart=/home/geocoder/apps/main-site/venv/bin/gunicorn app:app --bind 127.0.0.1:3000 --workers 2
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Create log directory
mkdir -p /var/log/melissa-main
chown geocoder:geocoder /var/log/melissa-main

# Enable and start main service
systemctl daemon-reload
systemctl enable melissa-main
systemctl start melissa-main
systemctl status melissa-main
```

### Geocoder Service

```bash
# Create systemd service file for geocoder
cat > /etc/systemd/system/geocoder.service << 'EOF'
[Unit]
Description=Jamaica Geocoder Web Application
After=network.target

[Service]
Type=exec
User=geocoder
Group=geocoder
WorkingDirectory=/home/geocoder/apps/geocoder
Environment="PATH=/home/geocoder/apps/geocoder/venv/bin"
ExecStart=/home/geocoder/apps/geocoder/venv/bin/gunicorn web_app:app --bind 127.0.0.1:8000 --timeout 300 --workers 2 --access-logfile /var/log/geocoder/access.log --error-logfile /var/log/geocoder/error.log
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Create log directory
mkdir -p /var/log/geocoder
chown geocoder:geocoder /var/log/geocoder

# Enable and start geocoder service
systemctl daemon-reload
systemctl enable geocoder
systemctl start geocoder
systemctl status geocoder
```

## Configure Nginx for Both Apps

```bash
# Create nginx configuration for main website
cat > /etc/nginx/sites-available/melissa-main << 'EOF'
server {
    listen 80;
    server_name melissa-response.org www.melissa-response.org;

    client_max_body_size 16M;

    location / {
        # Adjust port based on your main app
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }
}
EOF

# Create nginx configuration for geocoder
cat > /etc/nginx/sites-available/geocoder << 'EOF'
server {
    listen 80;
    server_name geocode.melissa-response.org;

    client_max_body_size 16M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 300s;
        proxy_send_timeout 300s;
        proxy_read_timeout 300s;
    }
}
EOF

# Enable both sites
ln -s /etc/nginx/sites-available/melissa-main /etc/nginx/sites-enabled/
ln -s /etc/nginx/sites-available/geocoder /etc/nginx/sites-enabled/

# Remove default nginx site
rm -f /etc/nginx/sites-enabled/default

# Test and restart nginx
nginx -t
systemctl restart nginx
```

## Set up SSL with Let's Encrypt

```bash
# Make sure DNS is pointing to your droplet first!
# Then run certbot for all domains:
certbot --nginx \
  -d melissa-response.org \
  -d www.melissa-response.org \
  -d geocode.melissa-response.org \
  --non-interactive --agree-tos -m your-email@example.com

# Certbot will automatically configure SSL and redirect HTTP to HTTPS for all domains
```

## Useful Commands

```bash
# View logs for both apps
journalctl -u melissa-main -f    # Main website logs
journalctl -u geocoder -f        # Geocoder logs

# Restart services
systemctl restart melissa-main
systemctl restart geocoder

# Check status of all services
systemctl status melissa-main
systemctl status geocoder
systemctl status nginx

# Update geocoder application
su - geocoder
cd ~/apps/geocoder
git pull  # or upload new files
source venv/bin/activate
pip install -r requirements.txt
exit
systemctl restart geocoder

# Update main application
su - geocoder
cd ~/apps/main-site
git pull  # or upload new files
# Install dependencies based on your tech stack
exit
systemctl restart melissa-main

# Test nginx config
nginx -t

# Reload nginx (for config changes without downtime)
nginx -s reload
```

## Firewall Setup (Optional but Recommended)

```bash
# Configure UFW firewall
ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw enable
ufw status
```

## Monitoring

```bash
# Check if apps are running
systemctl status melissa-main
systemctl status geocoder

# Check nginx
systemctl status nginx

# Check disk space
df -h

# Check memory usage
free -h

# View active connections
ss -tulpn

# Check which ports are in use
netstat -tlnp | grep -E ':(3000|8000|80|443)'

# Monitor resource usage in real-time
htop  # Install with: apt install htop
```

## DNS Configuration

In your DNS provider (where melissa-response.org is hosted):

**Update/Add these A records to point to your DigitalOcean droplet:**

1. **Main domain:**
   - Name: `@` (or blank/root)
   - Type: `A`
   - Value: `YOUR_DROPLET_IP`
   - TTL: `3600` (or automatic)

2. **WWW subdomain:**
   - Name: `www`
   - Type: `A`
   - Value: `YOUR_DROPLET_IP`
   - TTL: `3600`

3. **Geocoder subdomain:**
   - Name: `geocode`
   - Type: `A`
   - Value: `YOUR_DROPLET_IP`
   - TTL: `3600`

**Migration Strategy:**
- Option 1: Update DNS all at once (5-10 min downtime during DNS propagation)
- Option 2: Test with geocode subdomain first, then migrate main site when ready

## Costs Comparison

### Running Both Apps on One Droplet

**DigitalOcean (Single Droplet for Both Apps):**
- $12/month (2GB RAM, 1 vCPU, 50GB SSD) - **Recommended**
- $18/month (2GB RAM, 2 vCPU, 60GB SSD) - Better performance
- Total: **$12-18/month for both apps**

**Render (Current Setup):**
- Main site + Geocoder: ~$14-50/month (depending on plan)
- Total: **$14-50/month**

**Savings: $2-38/month** with better specs and full control!

### Migration Options

**Option 1: Migrate Both Apps at Once**
- Move everything to DO in one go
- Simpler management
- Single point of control
- Cost: $12-18/month total

**Option 2: Hybrid Approach (Start Here)**
- Keep main site on Render temporarily
- Run geocoder on DO ($6/month basic droplet)
- Migrate main site later when ready
- Test the waters with lower risk

**Option 3: Stay Hybrid**
- Main site on Render
- Geocoder on DO
- Best if main site has specific Render features you need
- Cost: Render fee + $6/month

## Migration Checklist

- [ ] Create DigitalOcean droplet
- [ ] Deploy geocoder app (and optionally main app)
- [ ] Configure nginx for domain routing
- [ ] Set up SSL certificates with Let's Encrypt
- [ ] Update DNS records
- [ ] Test both domains work correctly
- [ ] Monitor for 24-48 hours
- [ ] Cancel Render subscription (if moving both apps)
