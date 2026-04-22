# Humanitarian Geocoder

A self-hosted geocoding service backed by [OCHA COD-AB](https://cod.unocha.org/) administrative boundary data. Supports ~80 countries out of the box. Converts street addresses and GPS coordinates into standardised UN P-codes (ADM0–ADM4), with a web UI for ad-hoc lookups and batch CSV processing.

## Features

- **~80 countries** — powered by the OCHA global COD-AB dataset loaded into PostGIS
- **Dynamic P-code output** — returns `adm0`–`adm4` pcode/name pairs for however many levels exist for a country
- **Flexible input** — street addresses (via Google Maps API) and GPS coordinates in the same file
- **Batch CSV/XLSX upload** — auth-protected; download enriched file with P-codes appended
- **Single address lookup** and **reverse geocode** (click map or POST lat/lon)
- **Interactive map** — country selector, map-click to geocode, boundary level filter
- **React SPA** — frontend built with React 18, TypeScript, and [Mantine](https://mantine.dev/) v9
- **REST API** — all endpoints return JSON

---

## Architecture

| Component | Role |
|-----------|------|
| **React + TypeScript** | SPA frontend (Vite, Mantine v9, react-leaflet) |
| **Flask** | Web server, REST API, and SPA static file host |
| **PostGIS** | Spatial boundary storage and `ST_Contains` P-code lookup |
| **Google Maps API** | Address → lat/lon geocoding (coordinates bypass this) |
| **scripts/ingest.py** | One-time/incremental COD-AB data loader |

---

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Google Maps API key ([get one here](https://console.cloud.google.com/google/maps-apis))
- Node.js 20+ (only needed for local frontend development — Docker handles it automatically)

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

The `--build` step compiles the React frontend in a Node 20 stage and copies the static assets into the Python image — no separate frontend step required.

This starts:
- **db** — PostGIS 16 (internal only — not exposed to the host; access via `docker compose exec db psql -U geocode`)
- **geocoder** — Flask app on port 8000 (serves both the API and the compiled SPA)

### 3. Load boundary data

Run the ingest script inside the `geocoder` container — this gives it direct DB access and the correct `DATABASE_URL` without any extra config:

```bash
# Auto-download from HDX and ingest everything (~80 countries)
docker compose exec geocoder python scripts/ingest.py

# Or copy a pre-downloaded file into the container's /data volume first, then ingest
docker compose cp data/global_admin_boundaries_matched_latest.gdb.zip geocoder:/data/
docker compose exec geocoder python scripts/ingest.py \
  --file /data/global_admin_boundaries_matched_latest.gdb.zip

# Single country only (faster for testing)
docker compose exec geocoder python scripts/ingest.py \
  --file /data/global_admin_boundaries_matched_latest.gdb.zip \
  --country JAM
```

> The script skips the download if the file already exists in `/data/` (the container's persistent `geodata` volume).

### 4. Open the app

http://localhost:8000

---

## Local Development (without rebuilding Docker)

Two processes are needed: the Flask API and the Vite dev server.

```bash
# Terminal 1 — start the database, then run Flask
docker compose up db -d

python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python web_app.py          # listens on http://localhost:5001
```

```bash
# Terminal 2 — run the Vite dev server
cd frontend
npm install                # first time only
npm run dev                # listens on http://localhost:5173
```

Open http://localhost:5173 in your browser. The Vite dev server proxies all `/api/*`, `/geocode*`, `/countries`, `/login`, `/logout`, and other Flask routes to `http://localhost:5001` automatically, so hot-module reloading works while talking to the real backend.

### Building for production manually

```bash
cd frontend && npm run build
```

This compiles TypeScript and outputs the SPA assets to `static/`. Flask's catch-all route then serves `static/index.html` for all non-API paths.

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
docker compose exec geocoder python scripts/ingest.py \
  --file /data/global_admin_boundaries_matched_latest.gdb.zip \
  --country MOZ
```

---

## Adding Countries Missing from the Global Dataset

The global `_matched_latest` file covers ~110 countries. Some countries are absent because their boundaries haven't completed the edge-matching process. These can be ingested individually from their per-country HDX COD-AB pages (`https://data.humdata.org/dataset/cod-ab-{iso3}`).

After every ingest run the script automatically:
1. Refreshes the `mv_countries` materialized view (the source for the country dropdown)
2. Calls `POST /api/cache/clear` on the running app if `APP_URL` is set — so the country list updates immediately without a restart

Set `APP_URL` in your `.env` to enable step 2. When running via `docker compose exec` the script runs inside the container, so use the internal Flask port:

```ini
APP_URL=http://localhost:5000
# APP_LOGIN_USERNAME=admin  # defaults to admin
# APP_LOGIN_PASSWORD=...    # defaults to LOGIN_PASSWORD if not set separately
```

> If you run the script from the host instead, use `APP_URL=http://localhost:8000` (the host-mapped port).

### Example: Federated States of Micronesia (FSM)

FSM is not in the global dataset but its shapefile is available at:
https://data.humdata.org/dataset/cod-ab-fsm

1. Download the shapefile and copy it into the container's data volume:

```bash
curl -L "https://data.humdata.org/dataset/dc71c13f-e848-4ddc-9074-17e608464b63/resource/7348d022-6726-438c-9b1c-0b5524b7dbfd/download/fsm_admbnda_shp.zip" \
  -o data/fsm_admbnda_shp.zip
docker compose cp data/fsm_admbnda_shp.zip geocoder:/data/
```

2. Ingest it:

```bash
docker compose exec geocoder python scripts/ingest.py \
  --file /data/fsm_admbnda_shp.zip \
  --country FSM
```

The script auto-detects that this is a per-country shapefile (not the global GDB format) and routes it through the appropriate ingest path. The global dataset ingest is unaffected. The country dropdown will update automatically once the script completes.

### Example: Solomon Islands (SLB)

SLB is not in the global dataset. Its HDX page (`https://data.humdata.org/dataset/cod-ab-slb`) provides boundaries as **separate shapefiles per admin level** (ADM1–ADM3). The bundled `slb_polbnda.zip` file contains a `.mdb` (Microsoft Access Database) which is not supported — use the per-level shapefiles instead.

1. Download each level and copy into the container:

```bash
curl -L ".../slb_admbnda_adm1.zip" -o data/slb_admbnda_adm1.zip
curl -L ".../slb_admbnda_adm2.zip" -o data/slb_admbnda_adm2.zip
curl -L ".../slb_admbnda_adm3.zip" -o data/slb_admbnda_adm3.zip
docker compose cp data/slb_admbnda_adm1.zip geocoder:/data/
docker compose cp data/slb_admbnda_adm2.zip geocoder:/data/
docker compose cp data/slb_admbnda_adm3.zip geocoder:/data/
```

2. Ingest each file:

```bash
docker compose exec geocoder python scripts/ingest.py --file /data/slb_admbnda_adm1.zip --country SLB
docker compose exec geocoder python scripts/ingest.py --file /data/slb_admbnda_adm2.zip --country SLB
docker compose exec geocoder python scripts/ingest.py --file /data/slb_admbnda_adm3.zip --country SLB
```

The country dropdown updates automatically after the final run.

### Adding a new country

When adding a country whose field names differ from the standard COD-AB schema (`adm{n}_pcode`, `adm{n}_name`), add an entry to `FIELD_OVERRIDES` in `scripts/ingest.py` before ingesting:

```python
FIELD_OVERRIDES: dict[str, dict[str, str]] = {
    # FSM uses ADM1NAME (no underscore) instead of ADM1_NAME
    "FSM": {"ADM1NAME": "adm1_name"},
    # Add further overrides here as needed
    "XYZ": {"P_Code_ADM1": "adm1_pcode", "Name_ADM1": "adm1_name"},
}
```

Also ensure the ISO3 → ISO2 mapping exists in `ISO3_TO_ISO2` (the script will print "no ISO2 mapping" and skip the country if it is absent). Most countries are already present; Pacific island nations and other smaller territories may need to be added.

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
| `APP_URL` | — | Base URL of the running app; if set, ingest script clears the in-memory cache after loading data |
| `APP_LOGIN_USERNAME` | `admin` | Username used by the ingest script to authenticate the cache-clear request |
| `APP_LOGIN_PASSWORD` | `admin` | Password used by the ingest script to authenticate the cache-clear request |
