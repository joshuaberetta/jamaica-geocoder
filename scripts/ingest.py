#!/usr/bin/env python3
"""
COD-AB boundary ingest pipeline.

Ingests OCHA COD-AB boundary files into the cod_adm PostGIS table.
Supports GeoPackage (.gpkg), ESRI File Geodatabase (.gdb), and zipped
versions of either (.gpkg.zip, .gdb.zip).  Run once for initial load;
re-run per-country for incremental updates.

If --file is omitted the script downloads the recommended dataset from HDX
(global_admin_boundaries_matched_latest.gdb.zip) into the data/ directory.

Usage:
    # Auto-download from HDX and ingest (recommended first-run)
    DATABASE_URL=postgresql://... python scripts/ingest.py

    # Use an already-downloaded file
    DATABASE_URL=postgresql://... python scripts/ingest.py --file data/global_admin_boundaries_matched_latest.gdb.zip

    # Ingest a single country (deletes and re-inserts that country's rows)
    DATABASE_URL=postgresql://... python scripts/ingest.py --file data/jam.gpkg --country JAM
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

LAYER_RE = re.compile(r"_adm(\d+)_", re.IGNORECASE)


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

    # Cast Polygon → MultiPolygon to match schema
    def to_multi(geom):
        if geom is None:
            return None
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


def ingest_global_layer(file_path: str, layer_name: str,
                        country_filter: str | None = None) -> int:
    """
    Ingest one layer from the global matched GDB format (admin0, admin1, …).
    Each layer contains all countries; country is identified by an ISO field.
    Rows are grouped by country and inserted with delete-then-insert per (iso2, adm_level).
    """
    m = GLOBAL_LAYER_RE.match(layer_name)
    if not m:
        return 0
    adm_level = int(m.group(1))

    print(f"\nReading {layer_name} (ADM{adm_level}) — this may take a while...")
    gdf = gpd.read_file(file_path, layer=layer_name)
    gdf = gdf.to_crs("EPSG:4326")

    cols = list(gdf.columns)
    iso3_col = _find_col(cols, ISO3_FIELD_CANDIDATES)
    iso2_col = _find_col(cols, ISO2_FIELD_CANDIDATES)

    if not iso3_col and not iso2_col:
        print(f"  SKIP {layer_name}: no ISO country code column found.")
        print(f"  Available columns: {cols}")
        return 0

    id_col = iso3_col or iso2_col
    all_iso_vals = sorted(gdf[id_col].dropna().unique())

    # Apply country filter
    if country_filter:
        cf = country_filter.upper()
        all_iso_vals = [
            v for v in all_iso_vals
            if v.upper() == cf
            or iso3_to_iso2(v.upper()) == cf
            or (iso2_col and gdf.loc[gdf[id_col] == v, iso2_col].iloc[0].upper() == cf
                if iso2_col else False)
        ]
        if not all_iso_vals:
            print(f"  No rows found for country filter '{country_filter}'")
            return 0

    # Normalize column names once for the whole layer
    col_map = normalize_columns(gdf, "")  # no iso3-specific overrides at this stage
    gdf = gdf.rename(columns=col_map)
    # Refresh id_col name after rename (it won't have changed — ISO cols don't match adm regex)

    total = 0
    for iso_val in all_iso_vals:
        iso_val_u = iso_val.upper()

        if iso3_col:
            iso3 = iso_val_u
            iso2 = iso3_to_iso2(iso3)
            if not iso2 and iso2_col:
                matches = gdf.loc[gdf[id_col] == iso_val, iso2_col].dropna()
                iso2 = matches.iloc[0].upper() if not matches.empty else None
        else:
            iso2 = iso_val_u
            iso3 = next((k for k, v in ISO3_TO_ISO2.items() if v == iso2), iso2)

        if not iso2:
            print(f"  SKIP {iso_val}: no ISO2 mapping")
            continue

        group = gdf[gdf[id_col] == iso_val].copy()

        country_name = None
        if "adm0_name" in group.columns:
            vals = group["adm0_name"].dropna().unique()
            if vals.size:
                country_name = str(vals[0])

        rows = _build_rows(group, iso2, iso3, country_name, adm_level)
        if not rows:
            continue

        _insert_rows(rows, iso2, adm_level)
        print(f"  {iso2} ({iso3}): {len(rows)} rows")
        total += len(rows)

    return total


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
    args = parser.parse_args()

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

    else:
        # Per-country COD-AB GeoPackage format
        cod_layers = [l for l in layers if COD_AB_LAYER_RE.match(l)]
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


if __name__ == "__main__":
    main()

