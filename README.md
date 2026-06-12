# Humanitarian Geocoder

A self-hosted geocoding service backed by [OCHA COD-AB](https://cod.unocha.org/) administrative boundary data. Supports ~80 countries out of the box. Converts street addresses and GPS coordinates into standardised UN P-codes (ADM0–ADM4), with a web UI for ad-hoc lookups and batch CSV processing.

## Features

- **~80 countries** — powered by the OCHA global COD-AB dataset loaded into PostGIS
- **Dynamic P-code output** — returns `adm0`–`adm4` pcode/name pairs for however many levels exist for a country
- **Flexible input** — street addresses (via Google Maps API) and GPS coordinates in the same file
- **Batch CSV/XLSX upload** — auth-protected; download enriched file with P-codes appended
- **Single address lookup** and **reverse geocode** (click map or POST lat/lon)
- **Interactive map** — country selector, map-click to geocode, boundary level filter
- **XLSForm download** — per-country KoboCollect form with cascading admin-boundary `select_one` questions (and health zones where available), generated from the DB
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

Use the `?country=` query parameter to pre-select a country on load. Accepts ISO2, ISO3, or the lowercase country key (case-insensitive):

```
http://localhost:8000/?country=FSM
http://localhost:8000/?country=fsm
http://localhost:8000/?country=FM
```

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

## Adding Secondary Boundary Layers (e.g. health zones)

Some countries have **non-administrative** boundary layers that overlap the ADM
hierarchy rather than nesting into it — for example the DRC's *zones de santé*
(health zones), each identified by a DHIS2 org-unit ID instead of a P-code. These
are loaded into a separate `secondary_boundaries` table and merged into geocode
output as `health_zone_name` / `health_zone_dhis2` / `health_zone_id` fields, in
addition to the usual `adm*` P-codes. The admin lookup for other countries is
unaffected (the fields simply don't appear when no secondary boundary matches).

#### 1. Get the data

The DRC health zones come from the OpenStreetMap RDC / *Référentiel Géographique
Commun* export, published on HDX:
https://data.humdata.org/dataset/cod-rdc-zones-de-sante

Download the **GeoPackage** resource (`OSM_RDC_sante_zones_211212.gpkg`,
resource ID `8417072d-e942-4ba3-ab99-9994aeb42b3e`) into `data/`. Use the
GeoPackage (`.gpkg`), **not** the shapefile (`.zip`) — the shapefile DBF format
truncates the `ref:dhis2` field name, losing the DHIS2 id.

```bash
curl -L "https://data.humdata.org/dataset/cod-rdc-zones-de-sante/resource/8417072d-e942-4ba3-ab99-9994aeb42b3e/download/osm_rdc_sante_zones_211212.gpkg" \
  -o data/osm_rdc_sante_zones_211212.gpkg
```

> If the direct link 404s (HDX occasionally re-slugs datasets), open the dataset
> page above and use the GeoPackage resource's **Download** button.

#### 2. Ingest it

Ingest uses the `--secondary-boundary <type>` flag together with `--file` and
`--country` (ISO3 — the source file has no country column):

```bash
docker compose cp data/osm_rdc_sante_zones_211212.gpkg geocoder:/data/
docker compose exec geocoder python scripts/ingest.py \
  --file /data/osm_rdc_sante_zones_211212.gpkg \
  --country COD \
  --secondary-boundary health
```

The ingest re-creates the `secondary_boundaries` table if it doesn't exist yet
(so existing production databases provisioned before this feature need no manual
migration — the `CREATE TABLE IF NOT EXISTS` runs automatically), and is
idempotent: re-running replaces that country + boundary-type's rows. If
`APP_URL` is set (see [Updating Boundary Data](#updating-boundary-data)) the
script clears the running app's cache automatically; otherwise restart the app
so the new layer is picked up.

Once loaded, the interactive map automatically shows a **"Health zones"** toggle
for the DRC (driven by `GET /api/secondary_types`); other countries are
unaffected.

To support a new secondary dataset, add a field mapping under
`SECONDARY_FIELD_MAPS` in `scripts/ingest.py` and (if it's a new boundary type) a
response-key prefix under `SECONDARY_KEY_PREFIX` in `geocode.py`.

A geocode against DRC then returns, for example:

```json
{
  "success": true,
  "country": "Democratic Republic of the Congo",
  "adm1_name": "Lualaba",
  "health_zone_name": "Kasaji",
  "health_zone_dhis2": "kiFDojGFG3x",
  "health_zone_id": "r10731780"
}
```

---

## XLSForms (KoboCollect cascading selects)

The app can generate a [KoboCollect](https://www.kobotoolbox.org/) **XLSForm** per
country with one cascading `select_one` question per admin level (province →
district → …) plus, where available, a health-zone select. Choices are sourced
from the database, so the form mirrors exactly what the geocoder can resolve.
The UI exposes a **"Download XLSForm"** button under the country selector on the
Map tab; it downloads `GET /xlsform?country=<ISO2>`.

The form mirrors `data/ahMwxZhoASRpbmSmaTErim.xlsx`:

- **survey** — `select_one level_n` per populated admin level, cascaded with
  `choice_filter = starts-with(name, ${level_{n-1}})` (P-code prefix). Countries
  with secondary boundaries get an extra `select_one health_zone` cascaded under
  the selected province (`choice_filter = adm1=${level_1}`).
- **choices** — admin rows store the **P-code** as the value (matching the
  geocoder's `adm{n}_pcode` output); health-zone rows store **`ref_dhis2`**
  (fallback `source_id`) and carry an `adm1` column assigning each zone to the
  province it overlaps most (computed via a PostGIS spatial join, since zones
  have no stored parent P-code).

Forms are **pre-generated to disk** (`$XLSFORM_DIR`, default `/data/xlsforms`)
since they only change when boundary layers change:

- `scripts/entrypoint.sh` pre-generates all forms at container startup.
- `POST /api/cache/clear` (called by the ingest script) regenerates them, so a
  re-ingest flows through automatically.
- The `/xlsform` endpoint falls back to generating on demand (and caching to
  disk) for any country whose file isn't present yet.

Generate manually for one or all countries:

```bash
# All countries into the default dir ($XLSFORM_DIR or /data/xlsforms)
docker compose exec geocoder python scripts/generate_xlsforms.py

# A single country into a custom dir
docker compose exec geocoder python scripts/generate_xlsforms.py --country CD --out /tmp/xlsforms
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

> For countries with secondary boundary layers loaded (see [Adding Secondary
> Boundary Layers](#adding-secondary-boundary-layers-eg-health-zones)), the
> `GET /geocode`, `POST /geocode_single`, and `POST /reverse_geocode` responses
> also include `health_zone_name` / `health_zone_dhis2` / `health_zone_id` when
> the point falls inside a health zone, and the batch `POST /geocode` output adds
> matching columns.

---

### `GET /api/secondary_types` — public

Distinct secondary (non-administrative) boundary types loaded for a country.
The map UI uses this to decide which overlay toggles to show. Returns an empty
list for countries with no such data.

| Param | Description |
|-------|-------------|
| `country` | ISO2 code, e.g. `CD` |

```bash
curl "http://localhost:8000/api/secondary_types?country=CD"
```

```json
{ "iso2": "CD", "types": ["health"] }
```

---

### `GET /secondary_boundaries.geojson` — public

Secondary boundary polygons for a country as GeoJSON (simplified for display),
cached in memory per `(country, type)`. Used by the map overlay.

| Param | Description |
|-------|-------------|
| `country` | ISO2 code (required), e.g. `CD` |
| `type` | Boundary type, default `health` |

```bash
curl "http://localhost:8000/secondary_boundaries.geojson?country=CD&type=health"
```

Each feature's `properties` carry `name`, `ref_dhis2`, and `source_id`:

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "geometry": { "type": "Polygon", "coordinates": [/* ... */] },
      "properties": { "name": "Kasaji", "ref_dhis2": "kiFDojGFG3x", "source_id": "r10731780" }
    }
  ]
}
```

---

### `GET /xlsform` — public

Download a KoboCollect XLSForm for a country with cascading admin-boundary
`select_one` questions (and a health-zone select where available). Served from
the pre-generated cache on disk; generated on demand and cached if missing. See
[XLSForms](#xlsforms-kobocollect-cascading-selects).

| Param | Description |
|-------|-------------|
| `country` | ISO2 code (required), e.g. `CD` |

```bash
curl -OJ "http://localhost:8000/xlsform?country=CD"
```

Returns the `.xlsx` with a `Content-Disposition: attachment; filename="CD (…)​.xlsx"`
header. `400` if `country` is missing; `404` if the country has no admin levels.

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
  "stats": { "geocoded": 95, "not_geocoded": 5, "skipped": 0 },
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

### `POST /login` — public

Authenticates a session. Required before calling auth-protected endpoints.

**Request** (`application/x-www-form-urlencoded`):

| Field | Description |
|-------|-------------|
| `username` | Login username (default: `admin`) |
| `password` | Login password |

```bash
curl -c cookies.txt -X POST http://localhost:8000/login \
  -d "username=admin&password=your-password"
```

- **Success:** HTTP 302 redirect to `/`; sets a `session` cookie
- **Failure:** HTTP 401, plain-text body `Invalid username or password`

Pass `-c cookies.txt` to save the cookie and `-b cookies.txt` to send it on subsequent requests.

---

### `POST /logout` — public

Clears the session.

```bash
curl -b cookies.txt -X POST http://localhost:8000/logout
```

Returns HTTP 302 redirect to `/`.

---

### `POST /api/cache/clear` — **auth required**

Clears the in-memory countries, admin-boundaries, and secondary-boundaries caches, refreshes the `mv_countries` materialized view, and regenerates the cached XLSForms (best-effort — a generation failure does not fail the request). Pass an optional `country` (ISO2) to regenerate just that country's form instead of all of them. Called automatically by `scripts/ingest.py` when `APP_URL` is set (including after a `--secondary-boundary` ingest).

```bash
curl -b cookies.txt -X POST http://localhost:8000/api/cache/clear
```

```json
{ "status": "ok", "message": "Cache cleared" }
```

On view-refresh failure:

```json
{ "status": "error", "message": "Cache cleared but view refresh failed: <details>" }
```

---

## Error Responses

All endpoints return JSON errors unless otherwise noted. Common patterns:

| Situation | Status | Body |
|-----------|--------|------|
| Missing required param | 400 | `{"error": "..."}` |
| Invalid coordinates | 400 | `{"error": "Invalid latitude or longitude"}` |
| Not authenticated | 401 | `{"error": "Authentication required"}` |
| Address not found (GET /geocode) | 404 | `{"success": false, "error": "Could not geocode address"}` |
| Point outside boundaries (GET /geocode) | 404 | `{"success": false, "error": "Point outside known boundaries"}` |
| Point outside boundaries (POST endpoints) | 200 | `{"success": false, "error": "Point outside known boundaries"}` |
| Server error | 500 | `{"error": "..."}` |

> **Note:** `POST /geocode_single` and `POST /reverse_geocode` return HTTP 200 even when geocoding fails — check the `success` field.

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
| `XLSFORM_DIR` | `/data/xlsforms` | Directory for pre-generated XLSForms, served by `GET /xlsform` |
| `APP_URL` | — | Base URL of the running app; if set, ingest script clears the in-memory cache after loading data |
| `APP_LOGIN_USERNAME` | `admin` | Username used by the ingest script to authenticate the cache-clear request |
| `APP_LOGIN_PASSWORD` | `admin` | Password used by the ingest script to authenticate the cache-clear request |
