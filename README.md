# Humanitarian Geocoder

A self-hosted geocoding service backed by [OCHA COD-AB](https://cod.unocha.org/) administrative boundary data. Supports ~80 countries out of the box. Converts street addresses and GPS coordinates into standardised UN P-codes (ADM0–ADM4), with a web UI for ad-hoc lookups and batch CSV processing.

## Features

- **~80 countries** — powered by the OCHA global COD-AB dataset loaded into PostGIS
- **Dynamic P-code output** — returns `adm0`–`adm4` pcode/name pairs for however many levels exist for a country
- **Flexible input** — street addresses (via Google Maps API) and GPS coordinates in the same file
- **Batch CSV/XLSX upload** — auth-protected; download enriched file with P-codes appended
- **Single address lookup** and **reverse geocode** (click map or POST lat/lon)
- **Interactive map** — country selector, map-click to geocode, province filter
- **REST API** — all endpoints return JSON

---

## Architecture

| Component | Role |
|-----------|------|
| **Flask** | Web server and API |
| **PostGIS** | Spatial boundary storage and `ST_Contains` P-code lookup |
| **Google Maps API** | Address → lat/lon geocoding (coordinates bypass this) |
| **scripts/ingest.py** | One-time/incremental COD-AB data loader |

---

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Google Maps API key ([get one here](https://console.cloud.google.com/google/maps-apis))

### 1. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and set at minimum:

```ini
POSTGRES_PASSWORD=choose-a-strong-password
GOOGLE_MAPS_API_KEY=your-google-api-key
LOGIN_PASSWORD=choose-a-strong-password
```

### 2. Start the stack

```bash
docker compose up --build -d
```

This starts:
- **db** — PostGIS 16 on port 5432 (also exposed to host for local dev)
- **geocoder** — Flask app on port 8000

### 3. Load boundary data

Download and ingest the global COD-AB dataset from HDX (~940 MB):

```bash
# Auto-download from HDX and ingest everything (~80 countries)
DATABASE_URL=postgresql://geocode:yourpassword@localhost:5432/geocode \
  python scripts/ingest.py

# Or point at an already-downloaded file
DATABASE_URL=... python scripts/ingest.py \
  --file data/global_admin_boundaries_matched_latest.gdb.zip

# Single country only (faster for testing)
DATABASE_URL=... python scripts/ingest.py \
  --file data/global_admin_boundaries_matched_latest.gdb.zip \
  --country JAM
```

> The script skips the download if the file already exists in `data/`. The `data/` directory is gitignored.

### 4. Open the app

http://localhost:8000

---

## Local Development (without rebuilding Docker)

Run Flask directly against the Dockerised DB:

```bash
# Start just the database
docker compose up db -d

# Install dependencies (first time)
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Run the app (reads .env automatically via python-dotenv)
python web_app.py
```

The app runs on http://localhost:5001.

---

## Production Deployment

### Docker Compose (recommended)

Set all secrets in `.env`, then:

```bash
docker compose up -d
```

Put Nginx in front for SSL:

```nginx
server {
    server_name geocode.yourdomain.org;

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

```bash
sudo certbot --nginx -d geocode.yourdomain.org
```

### Without Docker (Gunicorn + systemd)

```ini
# /etc/systemd/system/geocoder.service
[Unit]
Description=Humanitarian Geocoder
After=network.target postgresql.service

[Service]
User=geocoder
WorkingDirectory=/home/geocoder/humanitarian-geocoder
EnvironmentFile=/home/geocoder/humanitarian-geocoder/.env
ExecStart=/home/geocoder/humanitarian-geocoder/venv/bin/gunicorn \
    --workers 3 --bind unix:geocoder.sock -m 007 web_app:app

[Install]
WantedBy=multi-user.target
```

---

## Updating Boundary Data

Re-run the ingest script for a specific country to refresh its boundaries without touching others:

```bash
DATABASE_URL=... python scripts/ingest.py \
  --file data/global_admin_boundaries_matched_latest.gdb.zip \
  --country MOZ
```

---

## API Reference

All endpoints return JSON. Coordinates bypass the Google API — no quota consumed.

### `GET /countries` — public

List all ingested countries with map center and maximum admin level.

```bash
curl http://localhost:8000/countries
```

```json
[
  {
    "code": "JM",
    "iso3": "JAM",
    "name": "Jamaica",
    "key": "jm",
    "max_adm_level": 2,
    "map_center": { "lat": 18.1096, "lon": -77.2975, "zoom": 6 }
  }
]
```

---

### `GET /api/admin_levels` — public

Distinct ADM1 names for a country (used by the province filter).

| Param | Description |
|-------|-------------|
| `country` | ISO2 code, e.g. `JM` |

```bash
curl "http://localhost:8000/api/admin_levels?country=JM"
```

```json
{ "label": "ADM1", "values": ["Clarendon", "Hanover", "Kingston", "..."] }
```

---

### `GET /geocode` — public

Resolve P-codes from coordinates or an address string.

| Param | Required | Description |
|-------|----------|-------------|
| `lat` / `latitude` | if no `address` | Decimal latitude |
| `lon` / `longitude` | if no `address` | Decimal longitude |
| `address` | if no lat/lon | Street address or `"lat, lon"` string |
| `country` | no | ISO2 code to scope the lookup |

```bash
# Coordinate lookup
curl "http://localhost:8000/geocode?lat=17.9978&lon=-76.7936&country=JM"

# Address lookup
curl "http://localhost:8000/geocode?address=New+Kingston&country=JM"
```

```json
{
  "success": true,
  "latitude": 17.9978,
  "longitude": -76.7936,
  "country": "Jamaica",
  "country_code": "JM",
  "adm0_pcode": "JM",
  "adm0_name": "Jamaica",
  "adm1_pcode": "JM001",
  "adm1_name": "Kingston",
  "adm2_pcode": "JM001001",
  "adm2_name": "New Kingston"
}
```

> Address lookups also include `address` and `confidence` fields.

---

### `POST /geocode_single` — public

Geocode a single address or coordinate.

```bash
curl -X POST http://localhost:8000/geocode_single \
  -H "Content-Type: application/json" \
  -d '{"address": "New Kingston, Jamaica", "country": "JM"}'
```

Response shape identical to `GET /geocode`.

---

### `POST /reverse_geocode` — public

Look up P-codes for a known lat/lon.

```bash
curl -X POST http://localhost:8000/reverse_geocode \
  -H "Content-Type: application/json" \
  -d '{"latitude": 17.9978, "longitude": -76.7936, "country": "JM"}'
```

---

### `POST /geocode` — **auth required**

Batch geocode a CSV or Excel file. Login via `POST /login` first (sets a session cookie).

**Request** (multipart form):

| Field | Description |
|-------|-------------|
| `file` | CSV or `.xlsx` with an `address` column |
| `country` | ISO2 code (optional) |
| `format` | `csv` (default) or `xlsx` |
| `admin1_names[]` | Repeatable; filter output to these ADM1 names |

**Response:**

```json
{
  "success": true,
  "stats": { "total": 100, "successful": 95, "failed": 5, "skipped": 0 },
  "file_data": "<base64-encoded file>",
  "filename": "geocoded_addresses.csv",
  "mimetype": "text/csv"
}
```

---

### `GET /health` — public

```json
{ "status": "ok", "countries_loaded": 47 }
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | — | PostgreSQL connection string (required) |
| `GOOGLE_MAPS_API_KEY` | — | Google Maps / Geocoding API key (required for address lookups) |
| `POSTGRES_PASSWORD` | — | Password for the `geocode` DB user (used by docker-compose) |
| `SECRET_KEY` | dev key | Flask session secret — **change in production** |
| `LOGIN_USERNAME` | `admin` | Batch upload username |
| `LOGIN_PASSWORD` | `admin` | Batch upload password — **change in production** |
| `FLASK_ENV` | `production` | Set to `development` for debug mode |
