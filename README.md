# Humanitarian Geocoder

A self-hosted geocoding service backed by [OCHA COD-AB](https://cod.unocha.org/) administrative boundary data. Supports ~80 countries out of the box. Converts street addresses and GPS coordinates into standardised UN P-codes (ADM0–ADM4), with a web UI for ad-hoc lookups and batch CSV processing.

## Features

- **~80 countries** — powered by the OCHA global COD-AB dataset loaded into PostGIS
- **Dynamic P-code output** — returns `adm0`–`adm4` pcode/name pairs for however many levels exist for a country
- **Flexible input** — street addresses (via Google Maps API) and GPS coordinates in the same file
- **Batch CSV/XLSX upload** — token-authenticated; download enriched file with P-codes appended
- **Single address lookup** and **reverse geocode** (click map or POST lat/lon) — token-authenticated
- **Interactive map** — country selector, map-click to geocode, boundary level filter
- **XLSForm download** — per-country KoboCollect form with cascading admin-boundary `select_one` questions (and health zones where available), generated from the DB
- **Admin-boundary CSV lists** — per-country, per-level `.csv` endpoints (the XLSForm choices) for use as KoboToolbox external choice lists, with optional per-user/project translation columns (`label::Spanish (es)`, …)
- **Token auth + rate limiting** — DRF token authentication with per-scope request throttling; users managed via the Django admin
- **React SPA** — frontend built with React 19, TypeScript, and [Mantine](https://mantine.dev/) v9
- **REST API** — all endpoints return JSON; interactive OpenAPI docs at `/api/docs/`

---

## Architecture

| Component | Role |
|-----------|------|
| **React + TypeScript** | SPA frontend (Vite, Mantine v9, react-leaflet) |
| **Django + DRF** | Web server, REST API, token auth + throttling, and SPA static file host |
| **GeoDjango / PostGIS** | Spatial boundary storage and `ST_Contains` P-code lookup |
| **Google Maps API** | Address → lat/lon geocoding (coordinates bypass this) |
| **scripts/ingest.py** | One-time/incremental COD-AB data loader |

The backend is a Django project (`config/`) with apps under `apps/`:

| App | Responsibility |
|-----|----------------|
| `apps.geo` | GeoDjango models for the boundary tables, read/data endpoints (`/countries`, `*.geojson`, `/xlsform`), spatial resolvers |
| `apps.geocoding` | `/geocode`, `/geocode_single`, `/reverse_geocode` (Google API + P-code resolution) |
| `apps.accounts` | Token auth (`/api/token`, `/api/me`) and the `ensure_superuser` bootstrap command |
| `apps.boundary_csv` | Per-country admin-boundary `.csv` lists (`/boundaries/…`) + the boundary-CSV project/translation-column management API |
| `apps.core` | `/health`, `/api/cache/clear`, and the SPA catch-all |

The boundary tables (`cod_adm`, `secondary_boundaries`) and the `mv_countries` materialized view are owned by `db/schema.sql` + `scripts/ingest.py`; GeoDjango maps them as `managed = False` models, so Django migrations only create its own auth/token/admin/session tables — plus the `apps.boundary_csv` project/language tables (the one managed app).

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
DJANGO_SUPERUSER_PASSWORD=choose-a-strong-password
SECRET_KEY=a-random-secret-string
```

On startup the container creates/updates a Django superuser from
`DJANGO_SUPERUSER_USERNAME` (default `admin`) / `DJANGO_SUPERUSER_PASSWORD` and
mints an API token for it — this replaces the old hardcoded login.

### 2. Start the stack

```bash
docker compose up --build -d
```

The `--build` step compiles the React frontend in a Node 20 stage and copies the static assets into the Python image — no separate frontend step required.

This starts:
- **db** — PostGIS 16 (internal only — not exposed to the host; access via `docker compose exec db psql -U geocode`)
- **geocoder** — Django app (gunicorn) on port 8000 (serves both the API and the compiled SPA)

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

Two processes are needed: the Django API and the Vite dev server.

```bash
# Terminal 1 — start the database, then run Django
docker compose up db -d

python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

export DATABASE_URL=postgresql://geocode:<POSTGRES_PASSWORD>@localhost:5432/geocode
python manage.py migrate                    # creates auth/token tables
DJANGO_SUPERUSER_PASSWORD=dev python manage.py ensure_superuser   # admin user + token
python manage.py runserver 0.0.0.0:8000     # listens on http://localhost:8000
```

> For local dev against the Dockerised DB, enable the host port mapping by keeping
> `docker-compose.override.yml` (publishes Postgres on `5432`). On a machine without
> a system GDAL/GEOS, Django auto-discovers the libraries bundled in the
> `fiona`/`shapely` wheels (see `config/settings.py`); set `GDAL_LIBRARY_PATH` /
> `GEOS_LIBRARY_PATH` explicitly if discovery fails.

```bash
# Terminal 2 — run the Vite dev server
cd frontend
npm install                # first time only
npm run dev                # listens on http://localhost:5173
```

Open http://localhost:5173 in your browser. The Vite dev server proxies all `/api/*`, `/geocode*`, `/countries`, `*.geojson`, `/boundaries/*`, `/xlsform`, and `/health` routes to `http://localhost:8000` automatically, so hot-module reloading works while talking to the real backend.

### Building for production manually

```bash
cd frontend && npm run build
```

This compiles TypeScript and outputs the SPA assets to `static/`. Django's catch-all route serves `static/index.html` for all non-API paths (WhiteNoise serves the hashed `assets/`).

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
    --workers 3 --bind unix:geocoder.sock -m 007 config.wsgi:application

[Install]
WantedBy=multi-user.target
```

> Run `python manage.py migrate` and `python manage.py collectstatic --noinput` once
> before starting the service. **With more than one worker, set `REDIS_URL`** so the
> cache-clear-on-ingest reaches every worker (the default in-memory cache is
> per-process); otherwise keep `--workers 1`.

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

Set `APP_URL` in your `.env` to enable step 2. The script authenticates the
cache-clear request with an admin **API token** (`APP_API_TOKEN`); if that isn't
set it falls back to `APP_LOGIN_USERNAME`/`APP_LOGIN_PASSWORD` → `POST /api/token`.
When running via `docker compose exec` the script runs inside the container, so
use the internal gunicorn port:

```ini
APP_URL=http://localhost:5000
APP_API_TOKEN=<admin token printed by `manage.py ensure_superuser`>
# Fallback if no token is set:
# APP_LOGIN_USERNAME=admin
# APP_LOGIN_PASSWORD=...
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
response-key prefix under `SECONDARY_KEY_PREFIX` in `apps/geo/services.py`.

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

Interactive OpenAPI docs are served at **`/api/docs/`** (Swagger UI) and
**`/api/redoc/`**; the raw schema is at `/api/schema/`.

**Authentication.** Protected endpoints use DRF **token auth**: obtain a token from
`POST /api/token`, then send it as an `Authorization: Token <token>` header.
All four geocoding endpoints (`GET /geocode`, `POST /geocode`, `POST /geocode_single`,
`POST /reverse_geocode`) **require a token** — they hit the paid Google API and/or
the boundary DB. The geo/data endpoints (`/countries`, `*.geojson`, `/xlsform`, the
boundary CSV serve, etc.) remain public. All endpoints are **rate-limited** (per-scope
throttling); the single-lookup geocoding endpoints have a tighter `geocode` scope, and
batch upload a `batch` scope.

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

### `GET /geocode` — **auth required**

Resolve P-codes from coordinates or an address string. Send a token as
`Authorization: Token <token>` (obtain one via `POST /api/token`).

| Param | Required | Description |
|-------|----------|-------------|
| `lat` / `latitude` | if no `address` | Decimal latitude |
| `lon` / `longitude` | if no `address` | Decimal longitude |
| `address` | if no lat/lon | Street address or `"lat, lon"` string |
| `country` | no | ISO2 code to scope the lookup |

```bash
# Coordinate lookup
curl "http://localhost:8000/geocode?lat=17.9978&lon=-76.7936&country=JM" \
  -H "Authorization: Token <token>"

# Address lookup
curl "http://localhost:8000/geocode?address=New+Kingston&country=JM" \
  -H "Authorization: Token <token>"
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

### `POST /geocode_single` — **auth required**

Geocode a single address or coordinate.

```bash
curl -X POST http://localhost:8000/geocode_single \
  -H "Authorization: Token <token>" \
  -H "Content-Type: application/json" \
  -d '{"address": "New Kingston, Jamaica", "country": "JM"}'
```

Response shape identical to `GET /geocode`.

---

### `POST /reverse_geocode` — **auth required**

Look up P-codes for a known lat/lon.

```bash
curl -X POST http://localhost:8000/reverse_geocode \
  -H "Authorization: Token <token>" \
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

### `GET /boundaries/{ISO2}/{level}.csv` — public

Per-level CSV of a country's admin boundaries — the same `(name, label)` rows
the XLSForm puts on its `choices` sheet — suitable for use directly as a
[KoboToolbox external choice list](https://support.kobotoolbox.org/dynamic_data_attachments.html)
(the URL ends in `.csv` as Kobo requires). Cached on disk-backed cache and
served with an ETag; throttle-exempt for automated fetches.

| Path segment | Description |
|--------------|-------------|
| `ISO2` | Country code, e.g. `JM` (case-insensitive) |
| `level` | Admin level `1`–`4`, or `health_zone` for the secondary health-zone list |

```bash
curl -OJ "http://localhost:8000/boundaries/JM/1.csv"     # parishes: name,label
curl -OJ "http://localhost:8000/boundaries/CD/health_zone.csv"  # name,label,adm1
```

`404` if the country/level has no rows. Admin-level CSVs have `name,label`;
health-zone CSVs add an `adm1` cascade column.

#### `GET /boundaries/{username}/{project}/{ISO2}/{level}.csv` — public

The same CSV with **per-project translation columns**. A signed-in user creates
a *boundary-CSV project* and configures translation headers on it, unique per
user + project (the serve URL itself needs no auth):

- **Primary label column** (`label_column_name`) — renames the base `label`
  header to an XLSForm translation (e.g. `label::English (en)`). Defaults to
  plain `label`.
- **Additional translation columns** — extra `label::…` columns appended after
  the primary label. Each duplicates the label value under its header — a
  ready-to-translate scaffold.

```bash
curl -OJ "http://localhost:8000/boundaries/josh/my-survey/JM/1.csv"
# label_column_name="label::English (en)", one extra column "label::Spanish (es)":
# name,label::English (en),label::English (en),label::Spanish (es)
# JM01,Kingston,Kingston,Kingston
```

Projects and their translation columns are managed (token auth, owner-scoped)
via the **boundary-CSV management API**:

| Method | URL | Description |
|--------|-----|-------------|
| `GET` | `/api/boundary-projects/` | List my projects |
| `POST` | `/api/boundary-projects/` | Create: `{name, slug}` |
| `GET` | `/api/boundary-projects/{slug}/?country=JM` | Detail; `csv_urls` lists per-level URLs for that country |
| `PATCH` | `/api/boundary-projects/{slug}/` | Update: `{name, label_column_name}` |
| `DELETE` | `/api/boundary-projects/{slug}/` | Delete a project |
| `POST` | `/api/boundary-projects/{slug}/languages/` | Add a column: `{header}` |
| `PATCH` | `/api/boundary-projects/{slug}/languages/{id}/` | Rename a column: `{header}` |
| `DELETE` | `/api/boundary-projects/{slug}/languages/{id}/` | Remove a column |

The **Boundary CSVs** tab in the web UI lists the default and per-project CSV
links for the selected country with copy buttons, and (when signed in) lets you
create projects and add/remove translation columns.

---

### `POST /geocode` — **auth required**

Batch geocode a CSV or Excel file. Obtain a token via `POST /api/token` first and
send it as `Authorization: Token <token>`.

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
{ "status": "ok", "countries_in_db": 47 }
```

---

### `POST /api/token` — public

Exchange username/password for an API token. Required before calling
auth-protected endpoints.

**Request** (JSON or form):

| Field | Description |
|-------|-------------|
| `username` | User name (bootstrap default: `admin`) |
| `password` | Password |

```bash
curl -X POST http://localhost:8000/api/token \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "your-password"}'
```

- **Success:** HTTP 200, `{"token": "<token>"}`
- **Failure:** HTTP 400 with field errors

Use the token on subsequent requests: `-H "Authorization: Token <token>"`.

---

### `GET /api/me` — **auth required**

Returns the authenticated user (the SPA uses this to confirm a stored token is
still valid). Replaces the old session-state check.

```bash
curl http://localhost:8000/api/me -H "Authorization: Token <token>"
```

```json
{ "logged_in": true, "username": "admin", "is_staff": true, "is_superuser": true }
```

> There is no logout endpoint — "logging out" simply means the client discards
> its token.

---

### `POST /api/cache/clear` — **admin auth required**

Clears the cached countries, admin-boundaries, and secondary-boundaries responses, refreshes the `mv_countries` materialized view, and regenerates the cached XLSForms (best-effort — a generation failure does not fail the request). Pass an optional `country` (ISO2) to regenerate just that country's form instead of all of them. Requires an **admin** token. Called automatically by `scripts/ingest.py` when `APP_URL` is set (including after a `--secondary-boundary` ingest).

```bash
curl -X POST http://localhost:8000/api/cache/clear \
  -H "Authorization: Token <admin-token>"
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
| Not authenticated | 401 | `{"detail": "Authentication credentials were not provided."}` |
| Authenticated but not admin (cache clear) | 403 | `{"detail": "You do not have permission..."}` |
| Rate limit exceeded | 429 | `{"detail": "Request was throttled. Expected available in N seconds."}` |
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
| `SECRET_KEY` | dev key | Django secret key — **change in production** |
| `DJANGO_SUPERUSER_USERNAME` | `admin` | Bootstrap admin username (created/updated on startup) |
| `DJANGO_SUPERUSER_PASSWORD` | — | Bootstrap admin password; if unset, no superuser is created — **set in production** |
| `DJANGO_SUPERUSER_EMAIL` | — | Optional bootstrap admin email |
| `DJANGO_DEBUG` | `false` | Set to `true` for debug mode |
| `ALLOWED_HOSTS` | `*` | Comma-separated allowed hostnames |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:5173` | Comma-separated origins allowed for cross-origin requests (Vite dev server) |
| `REDIS_URL` | — | If set, uses Redis for caching (required when running >1 worker) |
| `THROTTLE_ANON` / `THROTTLE_USER` | `120/min` / `600/min` | DRF rate limits for anonymous / authenticated requests |
| `THROTTLE_GEOCODE` / `THROTTLE_BATCH` | `30/min` / `5/min` | Rate limits for the Google-API and batch-upload scopes |
| `XLSFORM_DIR` | `/data/xlsforms` | Directory for pre-generated XLSForms, served by `GET /xlsform` |
| `APP_URL` | — | Base URL of the running app; if set, ingest script clears the cache after loading data |
| `APP_API_TOKEN` | — | Admin API token the ingest script uses to authenticate the cache-clear request |
| `APP_LOGIN_USERNAME` | `admin` | Fallback username (→ `/api/token`) if `APP_API_TOKEN` is unset |
| `APP_LOGIN_PASSWORD` | `admin` | Fallback password (→ `/api/token`) if `APP_API_TOKEN` is unset |

---

## Credits

- App logo / favicon (`static/logo.svg`): ["Globe Alt 9"](https://www.svgrepo.com/svg/globe-alt) from the [Scarlab Oval Line Icons](https://www.svgrepo.com/collection/scarlab-oval-line-icons/) collection by scarlab, via [SVG Repo](https://www.svgrepo.com/) — MIT License.
