# Plan: Health Zone Geocoding (DRC zones de santé)

## Goal

Geocode requests against DRC should return — in addition to the ADM0–ADM4 P-codes —
the **health zone** the point falls in: its name and its DHIS2 org-unit ID. Built
generically so other countries' health/secondary boundary layers can be added later
with no code changes (just an ingest run).

## Source data decision

Two files were downloaded into `data/`:

| File | Verdict |
|------|---------|
| `osm_rdc_sante_zones_211212.gpkg` (38.9 MB) | **USE THIS** |
| `osm_rdc_sante_zones_211212.zip` (13.7 MB, shapefile) | Skip — same data; shapefile would truncate `ref:dhis2` to 10 chars (DBF field-name limit) and is harder to read |

Verified contents of the `.gpkg`:

- 1 layer: `OSM_RDC_sante_zones_211212`, **520 features**, CRS **EPSG:4326**, geometry **MultiPolygon**
- Fields: `full_id`, `attribution`, `boundary` (`"health"`), `health_level` (all `"6"`),
  `name`, `ref:dhis2`, `alt_name`
- Completeness: 0 missing names, only 2 missing `ref:dhis2`
- Sample: `{name: "Biringi", ref:dhis2: "yS0pmMtanuT", health_level: "6"}`

### Why not load it into `cod_adm`

Health zones are a **parallel hierarchy** (`boundary=health`), not an administrative
level. They overlap ADM2/ADM3 spatially rather than nesting cleanly, and they have **no
P-code** (DHIS2 ID is the stable key instead). Inserting them into `cod_adm` would
corrupt the core geocode query, which returns the single deepest admin row via
`ORDER BY adm_level DESC LIMIT 1` — a health-zone row would either win incorrectly or
require fragile filtering. They belong in their own table, queried independently and
merged into the response.

## Database changes — `db/schema.sql`

Add a new generic secondary-boundary table:

```sql
-- Secondary (non-administrative) boundary layers, e.g. health zones.
-- Queried independently of cod_adm and merged into geocode output.
CREATE TABLE IF NOT EXISTS secondary_boundaries (
    id            SERIAL PRIMARY KEY,
    iso2          CHAR(2) NOT NULL,         -- 'CD'
    iso3          CHAR(3),                  -- 'COD'
    boundary_type TEXT    NOT NULL,         -- 'health' (matches OSM boundary tag)
    level         TEXT,                     -- source 'health_level' value, e.g. '6'
    name          TEXT,
    alt_name      TEXT,
    ref_dhis2     TEXT,                     -- DHIS2 org-unit id (NULL allowed)
    source_id     TEXT,                     -- OSM full_id, e.g. 'r10750251'
    attribution   TEXT,
    geom          GEOMETRY(MultiPolygon, 4326) NOT NULL
);

CREATE INDEX IF NOT EXISTS secbnd_geom_idx ON secondary_boundaries USING GIST (geom);
CREATE INDEX IF NOT EXISTS secbnd_iso2_type_idx
    ON secondary_boundaries (iso2, boundary_type);
```

Schema is applied idempotently (the app/entrypoint already runs `schema.sql`), so adding
these `CREATE ... IF NOT EXISTS` blocks is safe on existing databases — confirm
`scripts/entrypoint.sh` re-runs `schema.sql` on boot; if not, document a one-off
`psql $DATABASE_URL -f db/schema.sql`.

## Ingest changes — `scripts/ingest.py`

The current ingest is COD-AB-specific (layer-name regexes, adm-level parsing). Health
zones don't match either format, so add a **separate, explicitly-invoked ingest path**
rather than trying to auto-detect.

1. Add a CLI flag: `--secondary-boundary <type>` (e.g. `--secondary-boundary health`),
   used together with `--file` and `--country`.
2. When set, route to a new `ingest_secondary_boundary()` function that:
   - Reads the single layer via `geopandas.read_file(path)` (reuse the `/vsizip/`
     `resolve_file_path` helper).
   - Reprojects to EPSG:4326 (already is, but call `to_crs` defensively).
   - Forces 2D + `MultiPolygon` using the existing `to_multi` helper logic.
   - Maps source fields → table columns (`name`, `alt_name`, `ref:dhis2` → `ref_dhis2`,
     `full_id` → `source_id`, `boundary` → `boundary_type`, `health_level` → `level`,
     `attribution`). Field names are passed via a small dict so a different secondary
     dataset can override them.
   - Resolves `iso2`/`iso3` from the `--country` arg (required for secondary
     boundaries — there is no ISO column in the source).
   - `DELETE FROM secondary_boundaries WHERE iso2=:iso2 AND boundary_type=:type` then
     bulk-insert (same delete-then-insert pattern as `ingest_layer`).
3. Leave the existing COD-AB / global-GDB paths untouched.

Ingest command (documented in README later):

```bash
docker compose cp data/osm_rdc_sante_zones_211212.gpkg geocoder:/data/
docker compose exec geocoder python scripts/ingest.py \
  --file /data/osm_rdc_sante_zones_211212.gpkg \
  --country COD \
  --secondary-boundary health
```

## Lookup changes — `geocode.py`

Add a function parallel to `resolve_pcodes`:

```python
def resolve_secondary_boundaries(lat, lon, iso2=None) -> dict:
    """Return {'health_zone_name', 'health_zone_dhis2', 'health_zone_id'} etc.
    for any secondary boundary containing the point. Empty dict if none."""
```

- Query `secondary_boundaries` with the same GIST `ST_Contains` predicate, scoped by
  `iso2` when provided.
- For each matching `boundary_type`, emit prefixed keys. For `health`:
  `health_zone_name`, `health_zone_dhis2`, `health_zone_id` (= `source_id`).
  Key prefix derived from `boundary_type` (`health` → `health_zone_*`) via a small map,
  so adding another type later is trivial.
- Returns a plain dict suitable for `response.update(...)`.

This keeps the core admin query unchanged (no perf/regression risk to the 80-country
path) and is a no-op for countries with no secondary rows.

## Wiring into responses — `web_app.py`

Three call sites already call `resolve_pcodes(...)`. At each, merge in the secondary
lookup using the **resolved point** (works for both coordinate and address inputs):

- `GET /geocode` (~line 386): after `pcodes`, `response.update(resolve_secondary_boundaries(lat, lon, iso2))`.
- `POST /reverse_geocode` and `POST /geocode_single` (~lines 561, 599): same merge.
- `POST /geocode` batch (~line 480): merge into each row's `pcodes` dict before the
  DataFrame concat, so the columns appear in the exported CSV/XLSX.

Guard so the dict-merge only adds keys when a zone is found (already handled by returning
`{}`). No change needed to error paths (point-outside-boundaries still keyed off the
admin lookup).

## Frontend changes

1. `frontend/src/api/types.ts` — add optional fields to `PcodeResult`:
   `health_zone_name?`, `health_zone_dhis2?`, `health_zone_id?`.
2. `frontend/src/components/PcodeResultCard.tsx` — after the ADM loop, push rows for
   the health-zone fields when present:
   - `Health Zone` → `health_zone_name`
   - `Health Zone DHIS2` → `health_zone_dhis2`
3. Optional (later): map popup ("Shape info") and a toggle to render the health-zone
   layer via a `secondary_boundaries.geojson` endpoint mirroring `/boundaries.geojson`.
   Out of scope for the first cut unless requested.

## Out of scope (first cut)

- Serving health-zone polygons as a map overlay layer (separate endpoint + layer toggle).
- Health levels other than 6 (data only contains level 6).
- Backfilling DHIS2 IDs for the 2 zones missing them.

## Testing

- Unit: extend `tests/` with a `resolve_secondary_boundaries` test using a known DRC
  point (pick a centroid from the gpkg) → asserts expected `health_zone_name`.
- Integration: `curl "/geocode?lat=..&lon=..&country=CD"` returns both ADM and
  `health_zone_*` fields.
- Regression: a Jamaica geocode (`country=JM`) returns **no** `health_zone_*` keys and
  is byte-identical to before — confirms the generic path is inert for other countries.
- Batch: upload a small DRC CSV, confirm `health_zone_name`/`health_zone_dhis2` columns
  appear in the output.

## Step order

1. `db/schema.sql` — add `secondary_boundaries` table + indexes; apply to DB.
2. `scripts/ingest.py` — add `--secondary-boundary` path; ingest the DRC gpkg.
3. `geocode.py` — add `resolve_secondary_boundaries`.
4. `web_app.py` — merge into the 4 call sites.
5. Frontend types + result card.
6. Tests + README "Adding secondary boundary layers" section.
