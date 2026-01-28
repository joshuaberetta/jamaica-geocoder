# Humanitarian Geocoder

A multi-country web interface for geocoding addresses and matching them to administrative boundaries. Designed to support humanitarian response efforts by providing easy country switching, robust address matching, and standardized P-code output.

## Features

- **Multi-country support**: Switch between supported countries (currently Jamaica and Mozambique).
- **Batch Processing**: Upload CSV files with multiple addresses.
- **Single Address Lookup**: Type or paste an address or coordinate for instant results.
- **Administrative Boundary Matching**: Automatically assigns P-codes (e.g., ADM1, ADM2) based on location using spatial joins.
- **Coordinate Handling**: Smart detection of existing coordinates to bypass API calls.
- **Improved Accuracy**: Multi-strategy geocoding tailored for difficult addresses.
- **Interactive Map**: Visualize results and click to identify regions.
- **Export**: Download results as CSV or Excel.

## Supported Countries

- **Jamaica**: Parishes (ADM1) and Communities (ADM2)
- **Mozambique**: Provinces (ADM1) and Districts (ADM2)

## Quick Start (Local Development)

### Prerequisites

- Python 3.10+
- Google Maps API Key

### Installation

1.  **Clone the repository:**
    ```bash
    git clone <repository-url>
    cd jamaica-geocoder
    ```

2.  **Install dependencies:**
    It is recommended to use a virtual environment.
    ```bash
    python -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    ```

3.  **Configure Environment:**
    Create a `.env` file in the root directory:
    ```ini
    GOOGLE_MAPS_API_KEY=your_google_maps_api_key
    SECRET_KEY=your_secret_key
    LOGIN_USERNAME=admin
    LOGIN_PASSWORD=secure_password
    ```

4.  **Run the Application:**
    Using the helper script (macOS/Linux):
    ```bash
    ./scripts/run_web.sh
    ```
    Or directly with Python:
    ```bash
    python web_app.py
    ```

5.  **Access:**
    Open http://localhost:5000 in your browser.

## Docker Deployment

### Build and Run

You can deploy the application using Docker Compose.

1.  Ensure your `.env` file is created (see above).
2.  Run:
    ```bash
    docker-compose up --build
    ```
3.  The application will be available at `http://localhost:8000` (mapped from container port 5000).

## Production Deployment

This application is designed to be deployed on a Linux server (e.g., DigitalOcean Droplet) using Nginx and Gunicorn.

### Architecture
- **Nginx** as a reverse proxy (handling SSL/TLS).
- **Gunicorn** as the application server.
- **Systemd** for process management.

### Deployment Overview

1.  **Server Setup**:
    - Ubuntu Server (2GB RAM recommended).
    - Install dependencies: `python3`, `pip`, `nginx`, `certbot`, `python3-certbot-nginx`.
    - Create a dedicated user (e.g., `geocoder`).

2.  **Application Setup**:
    - Clone repo to `/home/geocoder/jamaica-geocoder`.
    - Set up virtual environment and install requirements.
    - Configure `.env` with production keys.

3.  **Service Configuration**:
    Create a systemd service file `/etc/systemd/system/geocoder.service`:

    ```ini
    [Unit]
    Description=Gunicorn instance to serve Geocoder
    After=network.target

    [Service]
    User=geocoder
    Group=www-data
    WorkingDirectory=/home/geocoder/jamaica-geocoder
    Environment="PATH=/home/geocoder/jamaica-geocoder/venv/bin"
    EnvironmentFile=/home/geocoder/jamaica-geocoder/.env
    ExecStart=/home/geocoder/jamaica-geocoder/venv/bin/gunicorn --workers 3 --bind unix:geocoder.sock -m 007 web_app:app

    [Install]
    WantedBy=multi-user.target
    ```

4.  **Nginx Configuration**:
    Configure Nginx to proxy requests to the socket and handle SSL.

    ```nginx
    server {
        server_name geocode.yourdomain.org;

        location / {
            include proxy_params;
            proxy_pass http://unix:/home/geocoder/jamaica-geocoder/geocoder.sock;
        }
    }
    ```

5.  **Enable SSL**:
    ```bash
    sudo certbot --nginx -d geocode.yourdomain.org
    ```

## Development History & Improvements

- **Geocoding Success Rate**: Improved from ~20% to >90% for difficult addresses through smarter parsing and coordinate detection.
- **Input Flexibility**: Added support for direct coordinate input (e.g., `18.1234, -77.5678`) which bypasses the geocoding API for cost savings.
- **Admin Boundaries**: Integrated strict spatial joining to ensure points fall within valid administrative boundaries for the selected country.
