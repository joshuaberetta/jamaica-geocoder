# Plan: Rewrite as Self-Hosted COD-AB Geocoding Service (~80 Countries)

## Summary

Full rewrite of the existing Jamaica/Mozambique geocoder to support all OCHA COD-AB countries (~80).
The country-specific Python module pattern, hardcoded bounds validation, GeoJSON boundary files,
and in-memory geopandas spatial joins are all replaced. The CSV batch upload UX is preserved;
the underlying resolution layer moves to PostGIS. Auth is removed; the API is open.

---

## What Gets Deleted

Before writing new code, remove the following which have no role in the new design:

| Path | Reason |
|---|---|
| `countries/jamaica.py` | Replaced by DB-driven config |
| `countries/mozambique.py` | Replaced by DB-driven config |
| `countries/country_config.py` | Replaced by DB-driven config |
| `countries/__init__.py` | Module no longer needed |
| `boundaries/jamaica.geojson` | Replaced by PostGIS |
| `boundaries/mozambique.geojson` | Replaced by PostGIS |
| `boundaries/` (directory) | No longer needed |

---

## Architecture

### Stack

- **PostgreSQL + PostGIS** — spatial storage and GIST-indexed point-in-polygon queries
- **Flask** — thin REST API layer (retained from current app)
- **psycopg2** — direct DB connection from Python; replaces geopandas spatial join
- **geopandas** — retained only for the ingest pipeline script, not the live app
- **GDAL / ogr2ogr** — ingest of OCHA GeoPackages into PostGIS

### Why PostGIS replaces geopandas in-memory join

The current `spatial_join_boundaries()` loads the entire country GeoDataFrame into RAM on startup,
performs an in-memory `sjoin`, and falls back to a nearest-neighbour scan for unmatched points.
At 2 countries this is acceptable; at 80 countries (each potentially ADM0–ADM4) it is not.

PostGIS with a GIST spatial index resolves any point in any country in a single
`ST_Contains` query regardless of polygon count, with no data loaded into application memory.

---

## Data Source

### OCHA COD-AB

- **Global GeoPackage**: https://data.humdata.org/dataset/cod-ab-global — single `.gpkg`, multiple layers, ~80 countries, ADM0–ADM4 where available
- **Per-country packages**: `https://data.humdata.org/dataset/cod-ab-{iso3}` — used for partial updates
- **License**: Creative Commons Attribution for Intergovernmental Organisations
- **Geometry**: WGS84 (EPSG:4326) or national projection — ogr2ogr re-projects at ingest

### Field name inconsistency (the main normalization challenge)

| Schema | Pcode field | Name field | Example countries |
|---|---|---|---|
| Uppercase + `_EN` | `ADM2_PCODE` | `ADM2_EN` | NGA, SOM, SSD, UKR, most |
| Lowercase + `_NAME` | `adm2_pcode` | `adm2_name` | CMR, MOZ |
| Mixed / national | varies | varies | occasional outliers |

Normalization regex (same logic as the existing `conftest.py` mock and current country configs):
```
/^adm(\d+)_pcode$/i  →  adm{n}_pcode
/^adm(\d+)_(name|en)$/i  →  adm{n}_name
```

---

## Step 1: Database Schema

Create `db/schema.sql`:

```sql
CREATE EXTENSION IF NOT EXISTS postgis;

-- Normalized boundaries table — one row per boundary polygon at any admin level
CREATE TABLE cod_adm (
  id          SERIAL PRIMARY KEY,
  iso2        CHAR(2)   NOT NULL,   -- 'MZ', 'JM', 'NG', etc.
  iso3        CHAR(3),              -- 'MOZ', 'JAM', 'NGA'
  country_name TEXT,                -- 'Mozambique', 'Jamaica'
  adm_level   SMALLINT  NOT NULL,  -- 0=country, 1=province, 2=district, 3=sub-district, 4
  adm0_pcode  TEXT,
  adm0_name   TEXT,
  adm1_pcode  TEXT,
  adm1_name   TEXT,
  adm2_pcode  TEXT,
  adm2_name   TEXT,
  adm3_pcode  TEXT,
  adm3_name   TEXT,
  adm4_pcode  TEXT,
  adm4_name   TEXT,
  geom        GEOMETRY(MultiPolygon, 4326) NOT NULL
);

-- Spatial index — the key performance primitive
CREATE INDEX cod_adm_geom_idx     ON cod_adm USING GIST (geom);
-- Fast country + level filtering
CREATE INDEX cod_adm_iso2_idx     ON cod_adm (iso2);
CREATE INDEX cod_adm_level_idx    ON cod_adm (adm_level);
```

Apply with: `psql $DATABASE_URL -f db/schema.sql`

---

## Step 2: Ingest Pipeline

Create `scripts/ingest.py`. This script is run once (and again for updates); it is **not** part of the live app.

### 2a. Download data

```bash
# Get the global GeoPackage from HDX (URL varies; check the dataset page)
wget -O data/cod_ab_global.gpkg "https://data.humdata.org/dataset/cod-ab-global/..."
```

Or per-country for targeted updates:
```bash
wget -O data/jam.gpkg "https://data.humdata.org/dataset/cod-ab-jam/..."
```

### 2b. List available layers

```bash
ogrinfo data/cod_ab_global.gpkg | grep "Layer name"
# Layers are named like: jam_admbnda_adm1_..., moz_admbnda_adm2_...
# Convention: {iso3}_admbnda_adm{N}_{source}_{date}
```

### 2c. `scripts/ingest.py` logic

```python
import re
import os
import geopandas as gpd
from sqlalchemy import create_engine, text

DATABASE_URL = os.environ['DATABASE_URL']
GPKG_PATH = 'data/cod_ab_global.gpkg'

# Regex to normalize source field names → adm{n}_pcode / adm{n}_name
PCODE_RE = re.compile(r'^adm(\d+)_pcode$', re.IGNORECASE)
NAME_RE  = re.compile(r'^adm(\d+)_(name|en)$', re.IGNORECASE)

def extract_admin_level(layer_name: str) -> int | None:
    """Parse ADM level from layer name, e.g. 'jam_admbnda_adm2_...' → 2"""
    m = re.search(r'_adm(\d+)_', layer_name, re.IGNORECASE)
    return int(m.group(1)) if m else None

def normalize_columns(gdf: gpd.GeoDataFrame) -> dict:
    """Return mapping of source column → normalized name for pcode/name fields."""
    mapping = {}
    for col in gdf.columns:
        m = PCODE_RE.match(col)
        if m:
            mapping[col] = f'adm{m.group(1)}_pcode'
            continue
        m = NAME_RE.match(col)
        if m:
            mapping[col] = f'adm{m.group(1)}_name'
    return mapping

def ingest_layer(engine, layer_name: str, iso2: str, iso3: str, country_name: str):
    adm_level = extract_admin_level(layer_name)
    if adm_level is None:
        print(f"Skipping {layer_name}: could not determine admin level")
        return

    gdf = gpd.read_file(GPKG_PATH, layer=layer_name)
    gdf = gdf.to_crs('EPSG:4326')

    # Ensure geometry is MultiPolygon
    gdf['geometry'] = gdf['geometry'].apply(
        lambda g: g if g is None or g.geom_type == 'MultiPolygon'
        else __import__('shapely').geometry.MultiPolygon([g])
    )

    col_map = normalize_columns(gdf)
    gdf = gdf.rename(columns=col_map)

    # Build normalized rows
    rows = []
    for _, feat in gdf.iterrows():
        row = {
            'iso2': iso2,
            'iso3': iso3,
            'country_name': country_name,
            'adm_level': adm_level,
            'geom': feat.geometry.wkt,
        }
        for n in range(5):
            row[f'adm{n}_pcode'] = feat.get(f'adm{n}_pcode')
            row[f'adm{n}_name']  = feat.get(f'adm{n}_name')
        rows.append(row)

    with engine.begin() as conn:
        # Delete existing rows for this country + level before re-inserting
        conn.execute(text(
            "DELETE FROM cod_adm WHERE iso2=:iso2 AND adm_level=:level"
        ), {'iso2': iso2, 'level': adm_level})

        conn.execute(text("""
            INSERT INTO cod_adm
              (iso2, iso3, country_name, adm_level,
               adm0_pcode, adm0_name, adm1_pcode, adm1_name,
               adm2_pcode, adm2_name, adm3_pcode, adm3_name,
               adm4_pcode, adm4_name, geom)
            VALUES
              (:iso2, :iso3, :country_name, :adm_level,
               :adm0_pcode, :adm0_name, :adm1_pcode, :adm1_name,
               :adm2_pcode, :adm2_name, :adm3_pcode, :adm3_name,
               :adm4_pcode, :adm4_name,
               ST_Multi(ST_GeomFromText(:geom, 4326)))
        """), rows)

    print(f"Ingested {len(rows)} rows for {layer_name}")
```

Call this function for every layer that matches the COD-AB naming pattern. Countries and their ISO codes
are read directly from `adm0_pcode` / `adm0_name` fields in the data — no hardcoded list needed.

### 2d. Handling non-standard field names

A small number of country datasets will not match either regex. Maintain a manual override dict in `ingest.py`:

```python
FIELD_OVERRIDES = {
    # iso3 → {source_field: normalized_field}
    # Add entries as discovered during ingest
}
```

---

## Step 3: Rewrite `geocode.py`

Replace the geopandas-based implementation with a PostGIS query function. Keep the public function
signatures where possible to minimize breakage in `web_app.py`.

### 3a. Remove entirely

- `spatial_join_boundaries()` — replaced by PostGIS query
- `validate_coordinates()` calls — no bounds validation; PostGIS returns no row if the point is outside all boundaries
- `normalize_longitude()` — remove; no country-specific hemisphere correction
- All imports from `countries.country_config`
- Spelling correction logic in `geocode_address()`
- `location_bias` rectangle construction in `geocode_address()` (built from country bounds)
- `fallback_parishes` logic

### 3b. Add database connection

```python
import psycopg2
import psycopg2.extras
from urllib.parse import urlparse

DATABASE_URL = os.getenv('DATABASE_URL')

def get_db_conn():
    return psycopg2.connect(DATABASE_URL)
```

Use a connection per request (acceptable at low load). Add a simple connection pool
(e.g. `psycopg2.pool.SimpleConnectionPool`) if latency becomes a concern.

### 3c. Replace `spatial_join_boundaries()` with `resolve_pcodes()`

```python
def resolve_pcodes(lat: float, lon: float, iso2: str | None = None) -> dict | None:
    """
    Return the deepest-available admin P-codes for a WGS84 point.
    Returns None if the point falls outside all known boundaries.
    Optionally scoped to a single country via iso2.
    """
    query = """
        SELECT iso2, iso3, country_name, adm_level,
               adm0_pcode, adm0_name,
               adm1_pcode, adm1_name,
               adm2_pcode, adm2_name,
               adm3_pcode, adm3_name,
               adm4_pcode, adm4_name
        FROM cod_adm
        WHERE ST_Contains(geom, ST_SetSRID(ST_Point(%s, %s), 4326))
        {iso2_clause}
        ORDER BY adm_level DESC
        LIMIT 1
    """.format(iso2_clause="AND iso2 = %s" if iso2 else "")

    params = [lon, lat] + ([iso2] if iso2 else [])

    with get_db_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, params)
            row = cur.fetchone()

    if row is None:
        return None

    # Return only populated levels (omit None pcode/name pairs)
    result = {
        'country': row['country_name'],
        'country_code': row['iso2'],
    }
    for n in range(5):
        pcode = row.get(f'adm{n}_pcode')
        name  = row.get(f'adm{n}_name')
        if pcode:
            result[f'adm{n}_pcode'] = pcode
        if name:
            result[f'adm{n}_name'] = name
    return result
```

### 3d. Simplify `geocode_address()`

Remove country-specific parameters. The function should accept only the address string and
optionally a country name hint to append to the query. Remove all country config dependencies.

```python
def geocode_address(address: str, country_hint: str | None = None) -> tuple[float, float, str] | None:
    """
    Geocode a free-text address via Google Places API.
    Returns (lat, lon, confidence) or None.
    country_hint: optional country name appended to the query if not already present.
    """
    # Check if already coordinates
    coords = parse_coordinates(address)
    if coords:
        return (*coords, 'COORDINATES')

    if not GOOGLE_MAPS_API_KEY:
        return None

    query = address.strip()
    if country_hint and country_hint.lower() not in query.lower():
        query = f"{query}, {country_hint}"

    # Places API call (same logic as current, minus country bounds/region/components parameters)
    ...
```

### 3e. Simplify `parse_coordinates()`

Remove the `country_config` parameter and all bounds/hemisphere validation. The function becomes:

```python
def parse_coordinates(text: str) -> tuple[float, float] | None:
    """Parse 'lat, lon' from a string. Returns (lat, lon) or None."""
    ...
    # coord_pattern match and float conversion — same as current
    # No validate_coordinates() call
    # No normalize_longitude() call
    return (lat, lon)
```

### 3f. Simplify `geocode_dataframe()`

Remove `country_config` parameter. The function processes a DataFrame of addresses/coordinates
and returns a list of `(lat, lon, confidence)` tuples. P-code resolution is done separately
in `web_app.py` via `resolve_pcodes()`, not inside `geocode_dataframe()`.

```python
def geocode_dataframe(
    df: pd.DataFrame,
    address_column: str = 'address',
    delay: float = 0.1,
    country_hint: str | None = None,
) -> tuple[gpd.GeoDataFrame, dict]:
    ...
```

---

## Step 4: Rewrite `web_app.py`

### 4a. Remove

- All imports from `countries.country_config`
- `load_boundaries()` function and all boundary caches (`boundaries_cache`, etc.)
- `admin1_filter` logic (was province-level filter from boundary field name config)
- `/boundaries.geojson` endpoint (no GeoJSON files)
- Country-specific field name references (`admin_levels['level1']['pcode_field']` etc.)

### 4b. Startup

Replace boundary pre-loading with a DB connectivity check:

```python
def check_db():
    try:
        with get_db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM cod_adm LIMIT 1")
        print("Database connection OK")
    except Exception as e:
        print(f"WARNING: Database not reachable: {e}")
```

Call `check_db()` at startup (not blocking — app should still start if DB is temporarily unavailable).

### 4c. Country list endpoint

Replace the hardcoded `AVAILABLE_COUNTRIES` list with a DB query:

```python
@app.route('/api/countries')
def get_countries():
    with get_db_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT DISTINCT iso2, iso3, country_name,
                       MAX(adm_level) AS max_adm_level
                FROM cod_adm
                GROUP BY iso2, iso3, country_name
                ORDER BY country_name
            """)
            rows = cur.fetchall()
    return jsonify([dict(r) for r in rows])
```

### 4d. `GET /geocode` (coordinate/address → P-codes)

Replace geopandas join with `resolve_pcodes()`. The `country` parameter becomes an optional
`iso2` filter passed directly to the DB query:

```python
@app.route('/geocode', methods=['GET'])
def geocode_get():
    lat_raw = request.args.get('lat') or request.args.get('latitude')
    lon_raw = request.args.get('lon') or request.args.get('longitude')
    address_input = request.args.get('address', '').strip()
    iso2 = request.args.get('country', '').upper() or None  # optional filter

    if lat_raw and lon_raw:
        lat, lon = float(lat_raw), float(lon_raw)
    elif address_input:
        result = geocode_address(address_input)
        if not result:
            return jsonify({'success': False, 'error': 'Could not geocode address'}), 404
        lat, lon, confidence = result
    else:
        return jsonify({'error': 'Provide lat/lon or address'}), 400

    pcodes = resolve_pcodes(lat, lon, iso2=iso2)
    if not pcodes:
        return jsonify({'success': False, 'error': 'Point outside known boundaries'}), 404

    return jsonify({'success': True, 'latitude': lat, 'longitude': lon, **pcodes})
```

### 4e. `POST /geocode` (CSV batch upload)

The UX is unchanged: user uploads a CSV with an `address` column, gets back a geocoded CSV
with P-code columns appended. The implementation changes:

1. Call `geocode_dataframe()` to resolve all addresses to `(lat, lon)` — same as now
2. For each successfully geocoded row, call `resolve_pcodes(lat, lon, iso2=iso2)`
3. Merge returned dicts back into the DataFrame rows
4. Return CSV/XLSX download — same as now

Replace the `spatial_join_boundaries(points_gdf, boundaries)` call with a loop over rows:

```python
results = []
for _, row in points_gdf.iterrows():
    if row.geometry is None:
        results.append({})
        continue
    lat, lon = row.geometry.y, row.geometry.x
    pcodes = resolve_pcodes(lat, lon, iso2=iso2) or {}
    results.append(pcodes)

pcode_df = pd.DataFrame(results)
result_df = pd.concat([df.reset_index(drop=True), pcode_df], axis=1)
```

The output columns are now dynamic (whatever levels the DB returned) rather than hardcoded
`admin1_pcode` / `admin2_pcode`.

### 4f. `/api/admin_levels` endpoint

Replace with a DB query. Since there is no hardcoded field name, query directly:

```python
@app.route('/api/admin_levels')
def get_admin_levels():
    iso2 = request.args.get('country', '').upper()
    level = int(request.args.get('level', 1))
    name_col = f'adm{level}_name'

    with get_db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT DISTINCT {name_col}
                FROM cod_adm
                WHERE iso2 = %s AND adm_level >= %s AND {name_col} IS NOT NULL
                ORDER BY {name_col}
            """, [iso2, level])
            names = [r[0] for r in cur.fetchall()]
    return jsonify({'iso2': iso2, 'level': level, 'values': names})
```

---

## Step 5: Update `docker-compose.yml`

Add a PostGIS service. The app service gains `DATABASE_URL` and a dependency on the DB:

```yaml
services:
  db:
    image: postgis/postgis:16-3.4
    environment:
      POSTGRES_DB: geocode
      POSTGRES_USER: geocode
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./db/schema.sql:/docker-entrypoint-initdb.d/schema.sql
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U geocode"]
      interval: 10s
      timeout: 5s
      retries: 5

  geocoder:
    build:
      context: .
      dockerfile: Dockerfile
    ports:
      - "8000:5000"
    environment:
      - GOOGLE_MAPS_API_KEY=${GOOGLE_MAPS_API_KEY}
      - DATABASE_URL=postgresql://geocode:${POSTGRES_PASSWORD}@db:5432/geocode
      - FLASK_ENV=${FLASK_ENV:-production}
    depends_on:
      db:
        condition: service_healthy
    restart: unless-stopped

volumes:
  pgdata:
```

Remove the `./boundaries:/app/boundaries:ro` volume mount — no longer needed.

---

## Step 6: Update `requirements.txt`

```
requests
pandas
geopandas        # retained for ingest script only
shapely
python-dotenv
openpyxl
flask
flask-cors
flask-compress
gunicorn
psycopg2-binary
sqlalchemy       # used by ingest script
pytest
fiona            # needed by geopandas for GeoPackage reading in ingest
```

Remove: no new deps for the live app beyond `psycopg2-binary`.

---

## Step 7: Update `templates/index.html`

- Remove login/logout UI elements
- Replace hardcoded country dropdown (currently populated from `AVAILABLE_COUNTRIES`) with
  a fetch to `/api/countries` on page load — the dropdown is now database-driven
- Output column display: instead of hardcoded `admin1_name` / `admin2_name` column headers,
  detect `adm{n}_name` columns dynamically in the result rendering

---

## Step 8: Update Tests

### Remove

- All tests that mock `country_config`, `validate_coordinates`, `load_boundaries`
- `conftest.py` fixtures: `mock_country_config`, `mock_mozambique_config`, `sample_boundaries`
- `test_geocode.py`: `test_parse_coordinates` (bounds validation removed),
  `test_spatial_join_boundaries` (function removed)

### Add

- `conftest.py`: a `db_conn` fixture using a test PostGIS database (or `pytest-mock` of `get_db_conn`)
- `test_geocode.py`:
  - `test_parse_coordinates_no_bounds` — parse valid coordinate strings, no validation
  - `test_resolve_pcodes_mock` — mock `get_db_conn`, assert correct SQL params and result shaping
- `test_web_app.py`:
  - Update `GET /geocode` tests to not require country config or boundary fixture
  - Update `POST /geocode` (batch) test to mock `resolve_pcodes` per row
  - Update login/logout tests to use the same session fixture pattern as current `conftest.py`

---

## Step 9: Directory Structure After Rewrite

```
geocode.py                  # Rewritten: parse_coordinates, geocode_address, geocode_dataframe
web_app.py                  # Rewritten: DB-backed routes, no auth, no boundary caches
requirements.txt            # Updated
docker-compose.yml          # Updated: includes PostGIS service
Dockerfile                  # Unchanged
db/
    schema.sql              # New: CREATE TABLE cod_adm + indexes
scripts/
    ingest.py               # New: one-time ingestion of COD-AB GeoPackages
    run_web.sh              # Unchanged
templates/
    index.html              # Updated: DB-driven country list, dynamic columns
tests/
    conftest.py             # Updated: remove country config fixtures
    test_geocode.py         # Updated: no bounds tests, resolve_pcodes tests
    test_web_app.py         # Updated: no auth, no boundary fixture
```

---

## Ingest Execution Order (First-Time Setup)

```bash
# 1. Start DB only
docker compose up db -d

# 2. Apply schema
psql $DATABASE_URL -f db/schema.sql

# 3. Download COD-AB data
mkdir -p data
wget -O data/cod_ab_global.gpkg "https://data.humdata.org/..."

# 4. Run ingest
DATABASE_URL=postgresql://... python scripts/ingest.py

# 5. Verify row counts
psql $DATABASE_URL -c "SELECT iso2, adm_level, COUNT(*) FROM cod_adm GROUP BY 1,2 ORDER BY 1,2;"

# 6. Start app
docker compose up geocoder -d
```

### Partial update (single country)

```bash
wget -O data/moz_updated.gpkg "https://data.humdata.org/dataset/cod-ab-moz/..."
DATABASE_URL=postgresql://... python scripts/ingest.py --country MOZ --file data/moz_updated.gpkg
```

The ingest script deletes and re-inserts per `(iso2, adm_level)` so partial updates are safe.

---

## API Reference (Post-Rewrite)

### `GET /geocode`

| Parameter | Description |
|---|---|
| `lat`, `lon` | WGS84 decimal degrees |
| `address` | Free-text address (geocoded via Google Places) |
| `country` | ISO2 code to scope the lookup (optional) |

**Response (success)**:
```json
{
  "success": true,
  "latitude": -18.143,
  "longitude": 35.296,
  "country": "Mozambique",
  "country_code": "MZ",
  "adm0_pcode": "MZ",
  "adm0_name": "Mozambique",
  "adm1_pcode": "MZ11",
  "adm1_name": "Nampula",
  "adm2_pcode": "MZ1101",
  "adm2_name": "Nampula City"
}
```

Only levels present in the DB for that point are included.

### `GET /api/countries`

Returns all ingested countries with max admin level available.

### `POST /geocode` (batch)

Requires login. Unchanged interface: multipart form upload with `file` (CSV/XLSX) and optional `country` (ISO2).
Output columns are now `adm0_pcode`, `adm0_name`, `adm1_pcode`, ... rather than `admin1_pcode`.

---

## Known Limitations

- **Schema normalization**: a small number of COD-AB datasets use non-standard field names not matched by the regex. These require entries in `FIELD_OVERRIDES` in `ingest.py` — discovered per country during ingest.
- **Polygon type**: some COD-AB layers use `Polygon` not `MultiPolygon`; the ingest script casts all to `MultiPolygon` to match the schema.
- **Boundary disputes**: COD-AB follows UN recognition; some borders are contested.
- **Island nations**: some are absent from COD-AB or have only ADM0.
- **Data freshness**: HDX updates vary by country. Manual re-ingest per country using the partial update command is sufficient for humanitarian operations cadence.
