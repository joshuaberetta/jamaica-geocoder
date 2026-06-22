#!/usr/bin/env python3
"""
COD-AB boundary ingest pipeline.

Ingests OCHA COD-AB boundary files into the cod_adm PostGIS table.
Supports GeoPackage (.gpkg), ESRI File Geodatabase (.gdb), Shapefile (.shp),
and zipped versions of any of the above.  Run once for initial load;
re-run per-country for incremental updates.

After ingest the script automatically:
  1. Refreshes the mv_countries materialized view (updates the country index).
  2. Clears the app's in-memory cache via POST /api/cache/clear if APP_URL is
     set in the environment (e.g. APP_URL=http://localhost:8000).
     APP_LOGIN_USERNAME / APP_LOGIN_PASSWORD are used for auth (default: admin).

If --file is omitted the script downloads the recommended dataset from HDX
(global_admin_boundaries_matched_latest.gdb.zip) into the data/ directory.

Usage:
    # Auto-download from HDX and ingest (recommended first-run)
    DATABASE_URL=postgresql://... python scripts/ingest.py

    # Use an already-downloaded file
    DATABASE_URL=postgresql://... python scripts/ingest.py --file data/global_admin_boundaries_matched_latest.gdb.zip

    # Ingest a single country (deletes and re-inserts that country's rows)
    DATABASE_URL=postgresql://... python scripts/ingest.py --file data/fsm_admbnda_shp.zip --country FSM

    # Ingest and notify a running app to clear its cache
    APP_URL=http://localhost:8000 DATABASE_URL=postgresql://... python scripts/ingest.py --file data/fsm_admbnda_shp.zip --country FSM
"""

import argparse
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

import fiona
import geopandas as gpd
import requests
from shapely.geometry import MultiPolygon
from sqlalchemy import create_engine, text

# ---------------------------------------------------------------------------
# HDX download
# ---------------------------------------------------------------------------

# The resource name to look for in the HDX dataset search results.
HDX_RESOURCE_NAME = "global_admin_boundaries_matched_latest.gdb.zip"
HDX_DATASET_QUERY = "global-admin-boundaries"
DEFAULT_DATA_DIR = Path(__file__).parent.parent / "data"


def download_from_hdx(dest_dir: Path = DEFAULT_DATA_DIR) -> Path:
    """
    Search HDX for the global matched admin boundaries dataset and download
    the .gdb.zip file into dest_dir if it isn't already present.
    Returns the local path to the downloaded file.
    """
    dest_path = dest_dir / HDX_RESOURCE_NAME
    if dest_path.exists():
        print(f"File already exists, skipping download: {dest_path}")
        return dest_path

    try:
        from hdx.api.configuration import Configuration
        from hdx.data.dataset import Dataset
    except ImportError:
        sys.exit(
            "ERROR: hdx-python-api is required for automatic download.\n"
            "Install it with: pip install hdx-python-api\n"
            "Or pass --file to use an already-downloaded file."
        )

    print("Connecting to HDX...")
    Configuration.create(hdx_site="prod", user_agent="humanitarian-geocoder", hdx_read_only=True)

    print(f"Searching HDX for '{HDX_DATASET_QUERY}'...")
    datasets = Dataset.search_in_hdx(HDX_DATASET_QUERY)
    resources = Dataset.get_all_resources(datasets)

    url = None
    for resource in resources:
        if resource["name"] == HDX_RESOURCE_NAME:
            url = resource["url"]
            break

    if not url:
        sys.exit(
            f"ERROR: Could not find resource '{HDX_RESOURCE_NAME}' on HDX.\n"
            f"Pass --file to specify a local file instead."
        )

    dest_dir.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {HDX_RESOURCE_NAME} from HDX (~940 MB)...")
    with requests.get(url, stream=True, timeout=300) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        downloaded = 0
        with open(dest_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                f.write(chunk)
                downloaded += len(chunk)
                if total:
                    pct = downloaded / total * 100
                    print(f"  {pct:.1f}% ({downloaded // 1_000_000} MB)", end="\r")
    print(f"\nDownload complete: {dest_path}")
    return dest_path

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    sys.exit("ERROR: DATABASE_URL environment variable is not set.")

engine = create_engine(DATABASE_URL)

# ---------------------------------------------------------------------------
# Field-name normalization
# ---------------------------------------------------------------------------

PCODE_RE = re.compile(r"^adm(\d+)_pcode$", re.IGNORECASE)
NAME_RE = re.compile(r"^adm(\d+)_(name|en)$", re.IGNORECASE)

# Manual overrides for datasets whose field names don't match the regex.
# Format: {iso3_upper: {source_field: normalized_field}}
# Add entries here as non-conforming countries are discovered during ingest.
FIELD_OVERRIDES: dict[str, dict[str, str]] = {
    # Example:
    # "XYZ": {"P_Code_ADM1": "adm1_pcode", "Name_ADM1": "adm1_name"},
    # FSM uses ADM1NAME (no underscore) instead of ADM1_NAME
    "FSM": {"ADM1NAME": "adm1_name"},
    # SLB uses COUNTRY instead of ADM0_NAME
    "SLB": {"COUNTRY": "adm0_name"},
}


def normalize_columns(gdf: gpd.GeoDataFrame, iso3: str) -> dict[str, str]:
    """Return a rename mapping from source column names to normalized adm{n} names."""
    mapping: dict[str, str] = {}

    # Apply manual overrides first
    overrides = FIELD_OVERRIDES.get(iso3.upper(), {})
    for src, dst in overrides.items():
        if src in gdf.columns:
            mapping[src] = dst

    # Apply regex normalization for remaining columns
    for col in gdf.columns:
        if col in mapping:
            continue
        m = PCODE_RE.match(col)
        if m:
            mapping[col] = f"adm{m.group(1)}_pcode"
            continue
        m = NAME_RE.match(col)
        if m:
            mapping[col] = f"adm{m.group(1)}_name"

    return mapping


# ---------------------------------------------------------------------------
# Layer helpers
# ---------------------------------------------------------------------------

LAYER_RE = re.compile(r"_adm(\d+)(?:_|$)", re.IGNORECASE)


def extract_admin_level(layer_name: str) -> int | None:
    """Parse ADM level from COD-AB layer name, e.g. 'jam_admbnda_adm2_ocha_20231001' → 2."""
    m = LAYER_RE.search(layer_name)
    return int(m.group(1)) if m else None


def extract_iso3(layer_name: str) -> str | None:
    """Extract the 3-letter ISO code from the start of a COD-AB layer name."""
    m = re.match(r"^([a-z]{3})_", layer_name, re.IGNORECASE)
    return m.group(1).upper() if m else None


ISO3_TO_ISO2: dict[str, str] = {
    # Common mappings. Extend as needed.
    "AFG": "AF", "AGO": "AO", "ALB": "AL", "AND": "AD", "ARE": "AE",
    "ARG": "AR", "ARM": "AM", "AUS": "AU", "AUT": "AT", "AZE": "AZ",
    "BDI": "BI", "BEL": "BE", "BEN": "BJ", "BFA": "BF", "BGD": "BD",
    "BGR": "BG", "BHR": "BH", "BIH": "BA", "BLR": "BY", "BLZ": "BZ",
    "BOL": "BO", "BRA": "BR", "BRN": "BN", "BTN": "BT", "BWA": "BW",
    "CAF": "CF", "CAN": "CA", "CHE": "CH", "CHL": "CL", "CHN": "CN",
    "CIV": "CI", "CMR": "CM", "COD": "CD", "COG": "CG", "COL": "CO",
    "COM": "KM", "CPV": "CV", "CRI": "CR", "CUB": "CU", "CYP": "CY",
    "CZE": "CZ", "DEU": "DE", "DJI": "DJ", "DNK": "DK", "DOM": "DO",
    "DZA": "DZ", "ECU": "EC", "EGY": "EG", "ERI": "ER", "ESP": "ES",
    "EST": "EE", "ETH": "ET", "FIN": "FI", "FJI": "FJ", "FRA": "FR",
    "FSM": "FM",
    "GAB": "GA", "GBR": "GB", "GEO": "GE", "GHA": "GH", "GIN": "GN",
    "GMB": "GM", "GNB": "GW", "GNQ": "GQ", "GRC": "GR", "GTM": "GT",
    "GUY": "GY", "HND": "HN", "HRV": "HR", "HTI": "HT", "HUN": "HU",
    "IDN": "ID", "IND": "IN", "IRL": "IE", "IRN": "IR", "IRQ": "IQ",
    "ISL": "IS", "ISR": "IL", "ITA": "IT", "JAM": "JM", "JOR": "JO",
    "JPN": "JP", "KAZ": "KZ", "KEN": "KE", "KGZ": "KG", "KHM": "KH",
    "KIR": "KI", "KWT": "KW", "LAO": "LA", "LBN": "LB", "LBR": "LR",
    "LBY": "LY", "LCA": "LC", "LKA": "LK", "LSO": "LS", "LTU": "LT",
    "LUX": "LU", "LVA": "LV", "MAR": "MA", "MDA": "MD", "MDG": "MG",
    "MDV": "MV", "MEX": "MX", "MKD": "MK", "MLI": "ML", "MLT": "MT",
    "MMR": "MM", "MNE": "ME", "MNG": "MN", "MOZ": "MZ", "MRT": "MR",
    "MUS": "MU", "MWI": "MW", "MYS": "MY", "NAM": "NA", "NER": "NE",
    "NGA": "NG", "NIC": "NI", "NLD": "NL", "NOR": "NO", "NPL": "NP",
    "NRU": "NR", "NZL": "NZ", "OMN": "OM", "PAK": "PK", "PAN": "PA",
    "PER": "PE", "PHL": "PH", "PLW": "PW", "PNG": "PG", "POL": "PL",
    "PRT": "PT", "PRY": "PY", "PSE": "PS", "QAT": "QA", "ROU": "RO",
    "RUS": "RU", "RWA": "RW", "SAU": "SA", "SDN": "SD", "SEN": "SN",
    "SGP": "SG", "SLB": "SB", "SLE": "SL", "SLV": "SV", "SOM": "SO",
    "SRB": "RS", "SSD": "SS", "STP": "ST", "SUR": "SR", "SVK": "SK",
    "SVN": "SI", "SWE": "SE", "SWZ": "SZ", "SYC": "SC", "SYR": "SY",
    "TCD": "TD", "TGO": "TG", "THA": "TH", "TJK": "TJ", "TKM": "TM",
    "TLS": "TL", "TON": "TO", "TTO": "TT", "TUN": "TN", "TUR": "TR",
    "TUV": "TV", "TZA": "TZ", "UGA": "UG", "UKR": "UA", "URY": "UY",
    "USA": "US", "UZB": "UZ", "VEN": "VE", "VNM": "VN", "VUT": "VU",
    "WSM": "WS", "YEM": "YE", "ZAF": "ZA", "ZMB": "ZM", "ZWE": "ZW",
}


def iso3_to_iso2(iso3: str) -> str | None:
    return ISO3_TO_ISO2.get(iso3.upper())


# ---------------------------------------------------------------------------
# Core ingest function
# ---------------------------------------------------------------------------


def ingest_layer(file_path: str, layer_name: str, iso3_override: str | None = None) -> int:
    """
    Load one layer into cod_adm.
    Deletes existing rows for (iso2, adm_level) before inserting.
    Returns number of rows inserted.
    """
    adm_level = extract_admin_level(layer_name)
    if adm_level is None:
        print(f"  SKIP {layer_name}: cannot determine admin level")
        return 0

    iso3 = (iso3_override or extract_iso3(layer_name) or "").upper()
    if not iso3:
        print(f"  SKIP {layer_name}: cannot determine ISO3 code")
        return 0

    iso2 = iso3_to_iso2(iso3)
    if not iso2:
        print(f"  SKIP {layer_name}: no ISO2 mapping for {iso3}")
        return 0

    print(f"  Loading {layer_name} (ISO3={iso3}, ISO2={iso2}, ADM{adm_level})...")

    gdf = gpd.read_file(file_path, layer=layer_name)
    gdf = gdf.to_crs("EPSG:4326")

    # Cast Polygon → MultiPolygon to match schema; force 2D to strip any Z coordinates
    def to_multi(geom):
        if geom is None:
            return None
        from shapely.ops import transform
        geom = transform(lambda x, y, *args: (x, y), geom)  # drop Z
        return geom if geom.geom_type == "MultiPolygon" else MultiPolygon([geom])

    gdf["geometry"] = gdf["geometry"].apply(to_multi)

    col_map = normalize_columns(gdf, iso3)
    gdf = gdf.rename(columns=col_map)

    # Derive country_name from adm0_name if present
    country_name = None
    if "adm0_name" in gdf.columns:
        vals = gdf["adm0_name"].dropna().unique()
        if len(vals) > 0:
            country_name = str(vals[0])

    rows = []
    for _, feat in gdf.iterrows():
        geom = feat.geometry
        if geom is None or geom.is_empty:
            continue
        row: dict = {
            "iso2": iso2,
            "iso3": iso3,
            "country_name": country_name,
            "adm_level": adm_level,
            "geom": geom.wkt,
        }
        for n in range(5):
            row[f"adm{n}_pcode"] = feat.get(f"adm{n}_pcode")
            row[f"adm{n}_name"] = feat.get(f"adm{n}_name")
        rows.append(row)

    if not rows:
        print(f"  No valid geometries in {layer_name}")
        return 0

    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM cod_adm WHERE iso2 = :iso2 AND adm_level = :level"),
            {"iso2": iso2, "level": adm_level},
        )
        conn.execute(
            text("""
                INSERT INTO cod_adm (
                    iso2, iso3, country_name, adm_level,
                    adm0_pcode, adm0_name, adm1_pcode, adm1_name,
                    adm2_pcode, adm2_name, adm3_pcode, adm3_name,
                    adm4_pcode, adm4_name, geom
                ) VALUES (
                    :iso2, :iso3, :country_name, :adm_level,
                    :adm0_pcode, :adm0_name, :adm1_pcode, :adm1_name,
                    :adm2_pcode, :adm2_name, :adm3_pcode, :adm3_name,
                    :adm4_pcode, :adm4_name,
                    ST_Multi(ST_GeomFromText(:geom, 4326))
                )
            """),
            rows,
        )

    print(f"  Inserted {len(rows)} rows for {layer_name}")
    return len(rows)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

# Per-country COD-AB GeoPackage: layer names like jam_admbnda_adm1_ocha_20231001
COD_AB_LAYER_RE = re.compile(r"^[a-z]{3}_admbnda_adm\d+", re.IGNORECASE)

# Global matched GDB: flat layers named admin0, admin1, admin2, admin3, admin4
GLOBAL_LAYER_RE = re.compile(r"^admin(\d+)$", re.IGNORECASE)

# Candidate field names for ISO3/ISO2 in global datasets
ISO3_FIELD_CANDIDATES = ["iso_3", "iso3", "alpha_3", "adm0_src"]
ISO2_FIELD_CANDIDATES = ["iso_2", "iso2", "alpha_2"]


def _find_col(columns: list[str], candidates: list[str]) -> str | None:
    """Return the first candidate that appears in columns (case-insensitive)."""
    lower = {c.lower(): c for c in columns}
    for cand in candidates:
        if cand.lower() in lower:
            return lower[cand.lower()]
    return None


def _build_rows(group: gpd.GeoDataFrame, iso2: str, iso3: str,
                country_name: str | None, adm_level: int) -> list[dict]:
    rows = []
    for _, feat in group.iterrows():
        geom = feat.geometry
        if geom is None or geom.is_empty:
            continue
        if geom.geom_type != "MultiPolygon":
            geom = MultiPolygon([geom])
        row: dict = {
            "iso2": iso2,
            "iso3": iso3,
            "country_name": country_name,
            "adm_level": adm_level,
            "geom": geom.wkt,
        }
        for n in range(5):
            row[f"adm{n}_pcode"] = feat.get(f"adm{n}_pcode")
            row[f"adm{n}_name"] = feat.get(f"adm{n}_name")
        rows.append(row)
    return rows


def _insert_rows(rows: list[dict], iso2: str, adm_level: int) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM cod_adm WHERE iso2 = :iso2 AND adm_level = :level"),
            {"iso2": iso2, "level": adm_level},
        )
        conn.execute(
            text("""
                INSERT INTO cod_adm (
                    iso2, iso3, country_name, adm_level,
                    adm0_pcode, adm0_name, adm1_pcode, adm1_name,
                    adm2_pcode, adm2_name, adm3_pcode, adm3_name,
                    adm4_pcode, adm4_name, geom
                ) VALUES (
                    :iso2, :iso3, :country_name, :adm_level,
                    :adm0_pcode, :adm0_name, :adm1_pcode, :adm1_name,
                    :adm2_pcode, :adm2_name, :adm3_pcode, :adm3_name,
                    :adm4_pcode, :adm4_name,
                    ST_Multi(ST_GeomFromText(:geom, 4326))
                )
            """),
            rows,
        )


def prune_padding_rows() -> int:
    """Remove "padding" rows the HDX global-matched dataset adds to give every
    country a uniform ADM4 depth.

    When a country's real boundaries stop at ADM2 (e.g. Afghanistan), the
    matched dataset still emits admin3/admin4 layers whose rows are copies of
    the parent unit with the deeper P-code column set equal to the parent's
    (e.g. adm3_pcode == adm2_pcode). A genuine child always gets a distinct,
    longer P-code, so deepest_pcode == parent_pcode is a reliable padding
    signal. This bloated cod_adm by ~43% (158k -> 90k rows, ~1.2 GB) and leaked
    duplicate adm3/adm4 codes into the geocode API response.

    Two cases, handled in order:
      1. Padding rows whose parent unit *also* exists at the level above (same
         P-code) are pure duplicates -> delete.
      2. Padding rows with no such parent are a real unit mis-filed one level
         too deep -> demote adm_level and null the padded deepest column,
         preserving the geometry/unit while dropping the duplicate code.

    Idempotent: re-running finds nothing once clean. Returns rows removed.
    """
    with engine.begin() as conn:
        # Case 2 first (demote orphans), so case 1 then sees their corrected
        # level and only deletes true duplicates that have a canonical parent.
        demoted_l4 = conn.execute(text("""
            UPDATE cod_adm a SET adm_level = 3, adm4_pcode = NULL, adm4_name = NULL
            WHERE a.adm_level = 4 AND a.adm4_pcode = a.adm3_pcode
              AND NOT EXISTS (SELECT 1 FROM cod_adm b
                              WHERE b.iso2 = a.iso2 AND b.adm_level = 3
                                AND b.adm3_pcode = a.adm3_pcode)
        """)).rowcount
        demoted_l3 = conn.execute(text("""
            UPDATE cod_adm a SET adm_level = 2, adm3_pcode = NULL, adm3_name = NULL
            WHERE a.adm_level = 3 AND a.adm3_pcode = a.adm2_pcode
              AND NOT EXISTS (SELECT 1 FROM cod_adm b
                              WHERE b.iso2 = a.iso2 AND b.adm_level = 2
                                AND b.adm2_pcode = a.adm2_pcode)
        """)).rowcount

        deleted = conn.execute(text("""
            DELETE FROM cod_adm WHERE id IN (
                SELECT id FROM cod_adm WHERE adm_level = 2 AND adm2_pcode = adm1_pcode
                UNION ALL SELECT id FROM cod_adm WHERE adm_level = 3 AND adm3_pcode = adm2_pcode
                UNION ALL SELECT id FROM cod_adm WHERE adm_level = 4 AND adm4_pcode = adm3_pcode
            )
        """)).rowcount

    print(f"  Pruned padding: deleted {deleted} duplicate rows, "
          f"demoted {demoted_l3 + demoted_l4} mis-filed rows.")
    return deleted


def set_ingest_complete(levels: list[int]) -> None:
    """Record that a full global ingest finished successfully. Writes a single
    row into ingest_meta keyed 'global_complete'. The deploy gate checks this
    instead of guessing completion from which admin levels happen to be
    present (which is dataset-dependent and was previously wrong)."""
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ingest_meta (
                key        TEXT PRIMARY KEY,
                value      TEXT,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))
        conn.execute(
            text("""
                INSERT INTO ingest_meta (key, value, updated_at)
                VALUES ('global_complete', :levels, now())
                ON CONFLICT (key)
                DO UPDATE SET value = EXCLUDED.value, updated_at = now()
            """),
            {"levels": ",".join(str(l) for l in levels)},
        )


def _ingested_iso2_at_level(adm_level: int) -> set[str]:
    """Return the set of iso2 codes already present in cod_adm at this admin
    level. Used for resumable ingest: because each (iso2, adm_level) is written
    in a single DELETE+INSERT transaction (_insert_rows), the presence of any
    row for a pair means that pair was fully committed and can be skipped on a
    re-run. This lets the ingest resume after a crash/timeout instead of
    restarting from scratch."""
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT DISTINCT iso2 FROM cod_adm WHERE adm_level = :level"),
                {"level": adm_level},
            ).fetchall()
        return {r[0] for r in rows if r[0]}
    except Exception:
        # Table may not exist yet on a truly fresh DB; treat as nothing done.
        return set()


def ingest_global_layer(file_path: str, layer_name: str,
                        country_filter: str | None = None) -> int:
    """
    Ingest one layer from the global matched GDB format (admin0, admin1, …).
    Streams features via fiona one-by-one and groups by country to avoid
    loading the entire global layer into memory at once.

    Resumable: countries already present at this admin level are skipped before
    geometry parsing, so a re-run after a crash/timeout picks up where it left
    off rather than re-ingesting committed work.
    """
    m = GLOBAL_LAYER_RE.match(layer_name)
    if not m:
        return 0
    adm_level = int(m.group(1))

    already_done = _ingested_iso2_at_level(adm_level)
    if already_done:
        print(f"\nStreaming {layer_name} (ADM{adm_level}) by country... "
              f"({len(already_done)} countries already ingested — skipping)")
    else:
        print(f"\nStreaming {layer_name} (ADM{adm_level}) by country...")

    import fiona
    from pyproj import CRS, Transformer
    from shapely.geometry import shape

    with fiona.open(file_path, layer=layer_name) as src:
        native_crs = CRS(src.crs)
        need_transform = not native_crs.equals(CRS("EPSG:4326"))
        transformer = (
            Transformer.from_crs(native_crs, CRS("EPSG:4326"), always_xy=True)
            if need_transform else None
        )

        cols = list(src.schema["properties"].keys())
        iso3_col = _find_col(cols, ISO3_FIELD_CANDIDATES)
        iso2_col = _find_col(cols, ISO2_FIELD_CANDIDATES)

        if not iso3_col and not iso2_col:
            print(f"  SKIP {layer_name}: no ISO country code column found.")
            print(f"  Available columns: {cols}")
            return 0

        id_col = iso3_col or iso2_col
        col_map = normalize_columns(
            gpd.GeoDataFrame(columns=cols + ["geometry"]), ""
        )

        # Build a column rename mapping for property keys
        prop_map: dict[str, str] = {}
        for c in cols:
            import re as _re
            m2 = PCODE_RE.match(c)
            if m2:
                prop_map[c] = f"adm{m2.group(1)}_pcode"
                continue
            m2 = NAME_RE.match(c)
            if m2:
                prop_map[c] = f"adm{m2.group(1)}_name"

        cf = country_filter.upper() if country_filter else None

        # Stream once, bucket features by ISO value (store as dicts, not GeoDataFrames)
        buckets: dict[str, list[dict]] = {}

        for feat in src:
            props = feat["properties"]
            iso_val = props.get(id_col)
            if not iso_val:
                continue
            iso_val_u = iso_val.upper()

            if cf:
                iso3_match = iso_val_u == cf if iso3_col else False
                iso2_match = iso3_to_iso2(iso_val_u) == cf if iso3_col else iso_val_u == cf
                if not (iso3_match or iso2_match):
                    continue

            # Resumable skip: drop features for countries already ingested at
            # this level before doing any (expensive) geometry parsing. iso2 is
            # derived the same way as the insert loop below.
            if already_done:
                iso2_for_feat = iso3_to_iso2(iso_val_u) if iso3_col else iso_val_u
                if iso2_for_feat in already_done:
                    continue

            geom_raw = feat.get("geometry")
            if not geom_raw:
                continue
            try:
                geom = shape(geom_raw)
                if transformer:
                    from shapely.ops import transform as shp_transform
                    geom = shp_transform(transformer.transform, geom)
                # Strip Z dimension if present
                if geom.has_z:
                    from shapely.ops import transform as shp_transform2
                    geom = shp_transform2(lambda x, y, *args: (x, y), geom)
                if geom.is_empty:
                    continue
                if geom.geom_type != "MultiPolygon":
                    geom = MultiPolygon([geom])
            except Exception:
                continue

            normalized: dict = {}
            for k, v in props.items():
                normalized[prop_map.get(k, k)] = v

            if iso_val_u not in buckets:
                buckets[iso_val_u] = []
            buckets[iso_val_u].append({"props": normalized, "geom": geom, "id_val": iso_val})

    total = 0
    for iso_val_u, feats in sorted(buckets.items()):
        if iso3_col:
            iso3 = iso_val_u
            iso2 = iso3_to_iso2(iso3)
            if not iso2 and iso2_col:
                iso2 = feats[0]["props"].get(iso2_col, "").upper() or None
        else:
            iso2 = iso_val_u
            iso3 = next((k for k, v in ISO3_TO_ISO2.items() if v == iso2), iso2)

        if not iso2:
            print(f"  SKIP {iso_val_u}: no ISO2 mapping")
            continue

        country_name = None
        for f in feats:
            cn = f["props"].get("adm0_name")
            if cn:
                country_name = str(cn)
                break

        rows = []
        for f in feats:
            geom = f["geom"]
            row: dict = {
                "iso2": iso2,
                "iso3": iso3,
                "country_name": country_name,
                "adm_level": adm_level,
                "geom": geom.wkt,
            }
            for n in range(5):
                row[f"adm{n}_pcode"] = f["props"].get(f"adm{n}_pcode")
                row[f"adm{n}_name"] = f["props"].get(f"adm{n}_name")
            rows.append(row)

        if not rows:
            continue

        _insert_rows(rows, iso2, adm_level)
        print(f"  {iso2} ({iso3}): {len(rows)} rows")
        total += len(rows)

    return total


# ---------------------------------------------------------------------------
# Secondary (non-administrative) boundary ingest, e.g. health zones
# ---------------------------------------------------------------------------

# Maps a secondary-boundary type to the source-field → table-column mapping
# for that dataset. Source fields not listed are ignored. Add new types here
# (or new field aliases) as further datasets are onboarded.
SECONDARY_FIELD_MAPS: dict[str, dict[str, str]] = {
    # OSM RDC zones de santé (Référentiel Géographique Commun)
    "health": {
        "name": "name",
        "alt_name": "alt_name",
        "ref:dhis2": "ref_dhis2",
        "full_id": "source_id",
        "health_level": "level",
        "attribution": "attribution",
    },
}


def ensure_secondary_table() -> None:
    """Create secondary_boundaries (and its indexes) if absent — keeps the
    secondary ingest self-contained on databases provisioned before this table
    existed (schema.sql only runs on a fresh volume)."""
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS secondary_boundaries (
                id            SERIAL PRIMARY KEY,
                iso2          CHAR(2) NOT NULL,
                iso3          CHAR(3),
                boundary_type TEXT    NOT NULL,
                level         TEXT,
                name          TEXT,
                alt_name      TEXT,
                ref_dhis2     TEXT,
                source_id     TEXT,
                attribution   TEXT,
                geom          GEOMETRY(MultiPolygon, 4326) NOT NULL
            )
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS secbnd_geom_idx "
            "ON secondary_boundaries USING GIST (geom)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS secbnd_iso2_type_idx "
            "ON secondary_boundaries (iso2, boundary_type)"
        ))


def ingest_secondary_boundary(
    file_path: str, boundary_type: str, iso3: str, layer_name: str | None = None
) -> int:
    """
    Load a single secondary-boundary layer (e.g. health zones) into
    secondary_boundaries. Deletes existing rows for (iso2, boundary_type)
    before inserting. Returns number of rows inserted.

    boundary_type: e.g. 'health'. Determines the source-field mapping used.
    iso3:          required — secondary datasets carry no ISO column.
    layer_name:    optional; defaults to the file's single layer.
    """
    iso3 = iso3.upper()
    iso2 = iso3_to_iso2(iso3)
    if not iso2:
        print(f"  SKIP: no ISO2 mapping for {iso3}")
        return 0

    field_map = SECONDARY_FIELD_MAPS.get(boundary_type)
    if field_map is None:
        print(
            f"  SKIP: unknown secondary boundary type '{boundary_type}'. "
            f"Known types: {sorted(SECONDARY_FIELD_MAPS)}"
        )
        return 0

    if layer_name is None:
        layers = fiona.listlayers(file_path)
        if len(layers) != 1:
            print(f"  Multiple layers found {layers}; specify one. Using first.")
        layer_name = layers[0]

    print(f"  Loading {layer_name} as '{boundary_type}' (ISO3={iso3}, ISO2={iso2})...")

    gdf = gpd.read_file(file_path, layer=layer_name)
    gdf = gdf.to_crs("EPSG:4326")

    from shapely.ops import transform

    def to_multi(geom):
        if geom is None:
            return None
        geom = transform(lambda x, y, *args: (x, y), geom)  # drop Z
        return geom if geom.geom_type == "MultiPolygon" else MultiPolygon([geom])

    gdf["geometry"] = gdf["geometry"].apply(to_multi)

    cols = ["name", "alt_name", "ref_dhis2", "source_id", "level", "attribution"]
    rows = []
    for _, feat in gdf.iterrows():
        geom = feat.geometry
        if geom is None or geom.is_empty:
            continue
        row: dict = {
            "iso2": iso2,
            "iso3": iso3,
            "boundary_type": boundary_type,
            "geom": geom.wkt,
        }
        for col in cols:
            row[col] = None
        for src, dst in field_map.items():
            val = feat.get(src)
            if val is not None and str(val).strip() != "":
                row[dst] = str(val)
        rows.append(row)

    if not rows:
        print(f"  No valid geometries in {layer_name}")
        return 0

    ensure_secondary_table()
    with engine.begin() as conn:
        conn.execute(
            text(
                "DELETE FROM secondary_boundaries "
                "WHERE iso2 = :iso2 AND boundary_type = :btype"
            ),
            {"iso2": iso2, "btype": boundary_type},
        )
        conn.execute(
            text("""
                INSERT INTO secondary_boundaries (
                    iso2, iso3, boundary_type, level,
                    name, alt_name, ref_dhis2, source_id, attribution, geom
                ) VALUES (
                    :iso2, :iso3, :boundary_type, :level,
                    :name, :alt_name, :ref_dhis2, :source_id, :attribution,
                    ST_Multi(ST_GeomFromText(:geom, 4326))
                )
            """),
            rows,
        )

    print(f"  Inserted {len(rows)} rows for {iso2} {boundary_type} boundaries")
    return len(rows)


def resolve_file_path(raw_path: str) -> str:
    """
    Return a fiona/GDAL-readable path.
    Zipped files (.zip) are accessed via GDAL's /vsizip/ virtual filesystem
    so they don't need to be extracted first.
    """
    p = Path(raw_path)
    if not p.exists():
        sys.exit(f"ERROR: File not found: {raw_path}")
    if p.suffix.lower() == ".zip":
        return f"/vsizip/{p.resolve()}"
    return str(p.resolve())


def main():
    parser = argparse.ArgumentParser(
        description="Ingest COD-AB boundaries (.gpkg, .gdb, or .zip of either) into PostGIS"
    )
    parser.add_argument(
        "--file",
        default=None,
        help=(
            "Path to .gpkg, .gdb, .gpkg.zip, or .gdb.zip file. "
            "If omitted, downloads the global matched dataset from HDX automatically."
        ),
    )
    parser.add_argument(
        "--country",
        default=None,
        help="ISO3 or ISO2 code to ingest (default: all countries)",
    )
    parser.add_argument(
        "--secondary-boundary",
        default=None,
        metavar="TYPE",
        help=(
            "Ingest a non-administrative boundary layer into secondary_boundaries "
            "instead of cod_adm, e.g. --secondary-boundary health. "
            "Requires --file and --country."
        ),
    )
    args = parser.parse_args()

    # Secondary-boundary path: a separate, explicitly-invoked ingest into
    # secondary_boundaries (does not touch cod_adm or the COD-AB detection).
    if args.secondary_boundary:
        if not args.file:
            sys.exit("ERROR: --secondary-boundary requires --file.")
        if not args.country:
            sys.exit("ERROR: --secondary-boundary requires --country (ISO3).")
        file_path = resolve_file_path(args.file)
        n = ingest_secondary_boundary(
            file_path, args.secondary_boundary.lower(), args.country
        )
        print(f"\nDone. {n:,} secondary-boundary rows inserted.")
        # Clear the app's in-memory cache so the new overlay/lookup is live
        # without a restart. No mv_countries refresh — that view is admin-only.
        app_url = os.environ.get("APP_URL", "").rstrip("/")
        if app_url:
            _notify_app(app_url)
        return

    if args.file:
        display_path = args.file
        file_path = resolve_file_path(args.file)
    else:
        local_path = download_from_hdx()
        display_path = str(local_path)
        file_path = resolve_file_path(str(local_path))

    layers = fiona.listlayers(file_path)
    print(f"Found {len(layers)} layers in {display_path}")
    for l in layers:
        print(f"  {l}")

    total_rows = 0

    if all(GLOBAL_LAYER_RE.match(l) for l in layers):
        # Global matched GDB format: admin0, admin1, admin2, admin3, admin4
        print("\nDetected global format — ingesting all countries per layer.")
        for layer in sorted(layers, key=lambda l: GLOBAL_LAYER_RE.match(l).group(1)):
            total_rows += ingest_global_layer(file_path, layer, args.country)

        # Mark a full (unfiltered) global ingest complete so deploys can
        # check-and-skip. The layer set here drives the dataset's real admin
        # levels (e.g. 1-4), which the old "levels 0-3 present" gate could
        # never satisfy. Only set when ingesting every country.
        if not args.country:
            ingested_levels = sorted(
                int(GLOBAL_LAYER_RE.match(l).group(1)) for l in layers
            )
            set_ingest_complete(ingested_levels)
            print(f"  Marked global ingest complete for levels {ingested_levels}.")

    else:
        # Per-country COD-AB GeoPackage format
        cod_layers = [l for l in layers if COD_AB_LAYER_RE.match(l) and "_eez" not in l.lower()]
        print(f"{len(cod_layers)} layers match COD-AB naming pattern")

        if not cod_layers:
            print("No matching layers found. Check the file format.")
            return

        if args.country:
            iso3 = args.country.upper()
            cod_layers = [l for l in cod_layers if l.upper().startswith(iso3)]
            print(f"Filtered to {len(cod_layers)} layers for {iso3}")

        if not cod_layers:
            print("No matching layers to ingest.")
            return

        for layer in sorted(cod_layers):
            iso3_override = args.country.upper() if args.country else None
            total_rows += ingest_layer(file_path, layer, iso3_override)

    print(f"\nDone. {total_rows:,} total rows inserted.")

    # ------------------------------------------------------------------
    # Post-ingest: drop dataset padding, refresh materialized view, clear cache
    # ------------------------------------------------------------------
    print("\nPruning HDX matched-dataset padding rows...")
    try:
        prune_padding_rows()
    except Exception as e:
        print(f"  WARNING: Could not prune padding rows: {e}")

    print("\nRefreshing mv_countries materialized view...")
    try:
        with engine.begin() as conn:
            conn.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY mv_countries"))
        print("  mv_countries refreshed.")
    except Exception as e:
        print(f"  WARNING: Could not refresh mv_countries: {e}")

    app_url = os.environ.get("APP_URL", "").rstrip("/")
    if app_url:
        _notify_app(app_url)


def _notify_app(app_url: str) -> None:
    """Call POST /api/cache/clear on the running app using an admin API token.

    The token is supplied via APP_API_TOKEN (mint one with
    `manage.py ensure_superuser`). Falls back to APP_LOGIN_* -> /api/token if no
    token is set, for convenience in dev.
    """
    token = os.environ.get("APP_API_TOKEN")
    if not token:
        username = os.environ.get("APP_LOGIN_USERNAME", "admin")
        password = os.environ.get("APP_LOGIN_PASSWORD", "admin")
        try:
            resp = requests.post(
                f"{app_url}/api/token",
                json={"username": username, "password": password},
                timeout=10,
            )
            if resp.ok:
                token = resp.json().get("token")
            else:
                print(f"  WARNING: Token obtain returned HTTP {resp.status_code} — cache not cleared.")
                return
        except requests.RequestException as e:
            print(f"  WARNING: Could not reach app at {app_url}: {e}")
            return

    print(f"\nClearing app cache at {app_url}...")
    try:
        resp = requests.post(
            f"{app_url}/api/cache/clear",
            headers={"Authorization": f"Token {token}"},
            timeout=10,
        )
        if resp.ok:
            print("  App cache cleared.")
        else:
            print(f"  WARNING: Cache clear returned HTTP {resp.status_code}: {resp.text}")
    except requests.RequestException as e:
        print(f"  WARNING: Could not reach app at {app_url}: {e}")


if __name__ == "__main__":
    main()

