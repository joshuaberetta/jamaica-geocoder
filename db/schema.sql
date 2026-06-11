-- COD-AB Geocoder Schema
-- Apply with: psql $DATABASE_URL -f db/schema.sql

CREATE EXTENSION IF NOT EXISTS postgis;

-- Normalized boundaries table.
-- One row per boundary polygon at any admin level.
-- All pcode/name fields use a consistent adm{n} convention regardless of source schema.
CREATE TABLE IF NOT EXISTS cod_adm (
    id           SERIAL PRIMARY KEY,
    iso2         CHAR(2)   NOT NULL,   -- ISO 3166-1 alpha-2, e.g. 'MZ'
    iso3         CHAR(3),              -- ISO 3166-1 alpha-3, e.g. 'MOZ'
    country_name TEXT,                 -- English country name, e.g. 'Mozambique'
    adm_level    SMALLINT  NOT NULL,   -- 0=country, 1=province, 2=district, 3=sub-district, 4
    adm0_pcode   TEXT,
    adm0_name    TEXT,
    adm1_pcode   TEXT,
    adm1_name    TEXT,
    adm2_pcode   TEXT,
    adm2_name    TEXT,
    adm3_pcode   TEXT,
    adm3_name    TEXT,
    adm4_pcode   TEXT,
    adm4_name    TEXT,
    geom         GEOMETRY(MultiPolygon, 4326) NOT NULL
);

-- Spatial index — the key performance primitive for ST_Contains queries.
CREATE INDEX IF NOT EXISTS cod_adm_geom_idx   ON cod_adm USING GIST (geom);

-- Fast country and level filtering.
CREATE INDEX IF NOT EXISTS cod_adm_iso2_idx   ON cod_adm (iso2);
CREATE INDEX IF NOT EXISTS cod_adm_level_idx  ON cod_adm (adm_level);

-- Materialized view: pre-aggregated country list for the /countries endpoint.
-- Eliminates the expensive ST_Extent(geom) scan on every cold-cache request.
-- Refresh with: REFRESH MATERIALIZED VIEW CONCURRENTLY mv_countries
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_countries AS
    SELECT
        iso2,
        iso3,
        country_name,
        MAX(adm_level)                              AS max_adm_level,
        ST_X(ST_Centroid(ST_Extent(geom)))          AS center_lon,
        ST_Y(ST_Centroid(ST_Extent(geom)))          AS center_lat
    FROM cod_adm
    GROUP BY iso2, iso3, country_name
    ORDER BY country_name;

-- Unique index required for CONCURRENTLY refresh (non-locking).
CREATE UNIQUE INDEX IF NOT EXISTS mv_countries_iso2_idx ON mv_countries (iso2);

-- ---------------------------------------------------------------------------
-- Secondary (non-administrative) boundary layers, e.g. health zones.
-- These form a parallel hierarchy that overlaps the cod_adm admin levels
-- rather than nesting into them, and are keyed by an external id (e.g. DHIS2)
-- instead of a P-code. Queried independently of cod_adm and merged into the
-- geocode output. Generic across countries and boundary types.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS secondary_boundaries (
    id            SERIAL PRIMARY KEY,
    iso2          CHAR(2) NOT NULL,         -- ISO 3166-1 alpha-2, e.g. 'CD'
    iso3          CHAR(3),                  -- ISO 3166-1 alpha-3, e.g. 'COD'
    boundary_type TEXT    NOT NULL,         -- OSM boundary tag, e.g. 'health'
    level         TEXT,                     -- source level value, e.g. '6'
    name          TEXT,
    alt_name      TEXT,
    ref_dhis2     TEXT,                     -- DHIS2 org-unit id (NULL allowed)
    source_id     TEXT,                     -- source feature id, e.g. OSM 'r10750251'
    attribution   TEXT,
    geom          GEOMETRY(MultiPolygon, 4326) NOT NULL
);

CREATE INDEX IF NOT EXISTS secbnd_geom_idx
    ON secondary_boundaries USING GIST (geom);
CREATE INDEX IF NOT EXISTS secbnd_iso2_type_idx
    ON secondary_boundaries (iso2, boundary_type);
