# Humanitarian Geocoder

A multi-country web interface for geocoding addresses and matching them to administrative boundaries. Designed to support humanitarian response efforts by providing easy country switching, robust address matching, and standardized P-code output.

## Features

- **Multi-country support**: Switch between supported countries (currently Jamaica and Mozambique).
- **Batch Processing**: Upload CSV files with multiple addresses.
- **Single Address Lookup**: Type or paste an address or coordinate for instant results.
- **Administrative Boundary Matching**: Automatically assigns P-codes (e.g., ADM1, ADM2) based on location using spatial joins.
- **Flexible Input Format**: The address column accepts both:
  - Street addresses: "123 Main St, Kingston, Jamaica" (geocoded via Google Maps API)
  - GPS coordinates: "18.1234, -77.5678" or "18,1234 -77,5678" (period or comma as decimal separator)
  - Mixed files: Some rows with addresses, some with coordinates
- **Smart Coordinate Detection**: Coordinates bypass API calls for cost savings and faster processing.
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

## API Reference

All endpoints return JSON. Endpoints marked **public** do not require authentication. Endpoints marked **auth required** require an active session (login first via the web UI or `POST /login`).

### `GET /geocode` — public

The simplest way to resolve P-codes. Accepts query parameters — no request body needed. Coordinates take priority over an address string; the `country` parameter is optional.

**Query parameters:**

| Param | Required | Description |
|-------|----------|-------------|
| `lat` / `latitude` | if no `address` | Decimal latitude |
| `lon` / `longitude` | if no `address` | Decimal longitude |
| `address` | if no `lat`/`lon` | Street address or `"lat, lon"` string |
| `country` | no | Country key: `jamaica` or `mozambique` (default: `mozambique`) |

**Examples:**
```bash
# Coordinate lookup (fastest — no geocoding API call)
curl "https://your-domain/geocode?lat=17.9978&lon=-76.7936&country=jamaica"

# Address lookup
curl "https://your-domain/geocode?address=New+Kingston,+Jamaica&country=jamaica"
```

**Response (success):**
```json
{
  "success": true,
  "latitude": 17.9978,
  "longitude": -76.7936,
  "admin1_pcode": "JM-01",
  "admin1_name": "Kingston",
  "admin1_label": "Parish",
  "admin2_pcode": "JM-0101",
  "admin2_name": "New Kingston",
  "admin2_label": "Community",
  "country": "Jamaica",
  "country_code": "JM"
}
```

> Address lookups also include `address` and `confidence` fields in the response.

---

### `POST /geocode_single` — public

Geocode a single address or GPS coordinate and return P-code data.

**Request** (JSON or form):

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `address` | string | yes | Street address (e.g. `"123 Main St, Kingston"`) or GPS coordinates (e.g. `"18.1234, -77.5678"`) |
| `country` | string | no | Country key: `jamaica` or `mozambique` (default: `mozambique`) |

**Example:**
```bash
curl -X POST https://your-domain/geocode_single \
  -H "Content-Type: application/json" \
  -d '{"address": "New Kingston, Jamaica", "country": "jamaica"}'
```

**Response (success):**
```json
{
  "success": true,
  "address": "New Kingston, Jamaica",
  "latitude": 17.9978,
  "longitude": -76.7936,
  "confidence": "high",
  "admin1_pcode": "JM-01",
  "admin1_name": "Kingston",
  "admin1_label": "Parish",
  "admin2_pcode": "JM-0101",
  "admin2_name": "New Kingston",
  "admin2_label": "Community",
  "country": "Jamaica",
  "country_code": "JM"
}
```

---

### `POST /reverse_geocode` — public

Look up administrative P-codes for a known latitude/longitude.

**Request** (JSON or form):

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `latitude` / `lat` | number | yes | Latitude in decimal degrees |
| `longitude` / `lon` | number | yes | Longitude in decimal degrees |
| `country` | string | no | Country key (default: `mozambique`) |

**Example:**
```bash
curl -X POST https://your-domain/reverse_geocode \
  -H "Content-Type: application/json" \
  -d '{"lat": 17.9978, "lon": -76.7936, "country": "jamaica"}'
```

**Response (success):** Same shape as `/geocode_single` but without `address` and `confidence` fields.

---

### `POST /geocode` — auth required

Batch geocode a CSV or Excel file. Returns the enriched file encoded as base64 JSON.

**Request** (multipart form):

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `file` | file | yes | CSV (semicolon-separated) or `.xlsx` file with an `address` column |
| `country` | string | no | Country key (default: `mozambique`) |
| `format` | string | no | Output format: `csv` (default) or `xlsx` |
| `limit` | integer | no | Process only the first N rows |
| `output_filename` | string | no | Base name for the downloaded file |
| `admin1_names[]` | string (repeatable) | no | Filter spatial join to specific ADM1 names |

**Response:**
```json
{
  "success": true,
  "stats": { "total": 100, "geocoded": 95, "failed": 5 },
  "file_data": "<base64-encoded file>",
  "filename": "geocoded_addresses.csv",
  "mimetype": "text/csv"
}
```

---

### `GET /api/admin_levels` — public

Return sorted ADM1 names for a country, useful for building filter dropdowns.

**Query parameters:**

| Param | Description |
|-------|-------------|
| `country` | Country key (default: `mozambique`) |

**Example:**
```bash
curl "https://your-domain/api/admin_levels?country=jamaica"
```

**Response:**
```json
{
  "country": "Jamaica",
  "level": "admin1",
  "label": "Parish",
  "values": ["Clarendon", "Hanover", "Kingston", "..."]
}
```

---

### `GET /boundaries.geojson` — public

Serve the administrative boundary GeoJSON for a country (WGS84). Supports `ETag` / `If-None-Match` caching and returns gzip-compressed data.

**Query parameters:**

| Param | Description |
|-------|-------------|
| `country` | Country key (default: `mozambique`) |

**Example:**
```bash
curl "https://your-domain/boundaries.geojson?country=jamaica"
```

---

### `GET /countries` — public

List all supported countries with their configurations.

**Response:**
```json
[
  {
    "code": "JM",
    "name": "Jamaica",
    "key": "jamaica",
    "map_center": [18.1096, -77.2975],
    "admin_levels": { "level1": { "label": "Parish", ... }, "level2": { ... } }
  }
]
```

---

### `GET /health` — public

Health check. Returns server status and which country boundary datasets are currently loaded.

**Response:**
```json
{
  "status": "ok",
  "countries_loaded": ["JM"],
  "available_countries": ["JM", "MZ"]
}
```

---

## Development History & Improvements

- **Geocoding Success Rate**: Improved from ~20% to >90% for difficult addresses through smarter parsing and coordinate detection.
- **Input Flexibility**: The address column now accepts both street addresses AND GPS coordinates:
  - Coordinates are automatically detected and used directly (no API call)
  - Addresses are geocoded via Google Maps API
  - All results (coordinates or geocoded) receive P-code assignments via spatial join
  - Mixed input files are fully supported
- **Admin Boundaries**: Integrated strict spatial joining to ensure points fall within valid administrative boundaries for the selected country.
