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
