#!/usr/bin/env python3
"""
Humanitarian Geocoder - Core geocoding functions backed by PostGIS.
"""

import json
import os
import re
import time
from typing import Any, Dict, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

import geopandas as gpd
import pandas as pd
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from shapely.geometry import Point

load_dotenv()

GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------


def get_db_conn():
    """Open and return a new psycopg2 connection."""
    return psycopg2.connect(DATABASE_URL)


# ---------------------------------------------------------------------------
# Coordinate parsing
# ---------------------------------------------------------------------------


def parse_coordinates(text: str) -> Optional[Tuple[float, float]]:
    """
    Parse a coordinate string into (lat, lon).
    Supports decimal point or comma as separator (European format).
    Returns None if the string does not look like valid coordinates.
    """
    if not text or pd.isna(text):
        return None

    text = str(text).strip().strip("()")

    coord_pattern = r"^(-?\d+[.,]?\d*)\s*[,\s]\s*(-?\d+[.,]?\d*)$"
    match = re.match(coord_pattern, text)
    if match:
        try:
            lat = float(match.group(1).replace(",", "."))
            lon = float(match.group(2).replace(",", "."))
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                return (lat, lon)
        except ValueError:
            pass

    return None


# ---------------------------------------------------------------------------
# PostGIS P-code resolution
# ---------------------------------------------------------------------------


def resolve_pcodes(
    lat: float, lon: float, iso2: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    Return the deepest-available admin boundary P-codes for a WGS84 point.

    Uses a GIST-indexed ST_Contains query against cod_adm.
    Returns None if the point falls outside all known boundaries.

    iso2: optional ISO 3166-1 alpha-2 code to scope the lookup to one country.
    """
    iso2_clause = "AND iso2 = %s" if iso2 else ""
    query = f"""
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
    """
    params = [lon, lat]
    if iso2:
        params.append(iso2.upper())

    try:
        with get_db_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(query, params)
                row = cur.fetchone()
    except Exception as e:
        print(f"Database error in resolve_pcodes({lat}, {lon}): {e}")
        return None

    if row is None:
        return None

    result: Dict[str, Any] = {
        "country": row["country_name"],
        "country_code": row["iso2"],
    }
    for n in range(5):
        pcode = row.get(f"adm{n}_pcode")
        name = row.get(f"adm{n}_name")
        if pcode:
            result[f"adm{n}_pcode"] = pcode
        if name:
            result[f"adm{n}_name"] = name

    return result


# ---------------------------------------------------------------------------
# Geocoding via Google APIs
# ---------------------------------------------------------------------------


def geocode_address(
    address: str,
    country_hint: Optional[str] = None,
) -> Optional[Tuple[float, float, str]]:
    """
    Geocode a free-text address using Google Places API.
    Returns (lat, lon, confidence) or None.

    If `address` already looks like coordinates, returns them directly with
    confidence='COORDINATES' and makes no API call.

    country_hint: optional country name appended to the query when not already present.
    """
    if not address or pd.isna(address):
        return None

    coords = parse_coordinates(str(address))
    if coords:
        return (*coords, "COORDINATES")

    if not GOOGLE_MAPS_API_KEY:
        print("Error: GOOGLE_MAPS_API_KEY not set.")
        return None

    query = str(address).strip()
    if country_hint and country_hint.lower() not in query.lower():
        query = f"{query}, {country_hint}"

    best_result = None
    best_quality = -1

    # --- Primary: Places Text Search ---
    try:
        places_url = (
            "https://maps.googleapis.com/maps/api/place/textsearch/json?"
            + urlencode({"query": query, "key": GOOGLE_MAPS_API_KEY})
        )
        with urlopen(places_url, timeout=10) as response:
            data = json.loads(response.read().decode())

        if data.get("status") == "OK" and data.get("results"):
            for result in data["results"]:
                result_types = set(result.get("types", []))
                location = result["geometry"]["location"]
                lat = float(location["lat"])
                lon = float(location["lng"])

                if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                    continue

                if "locality" in result_types:
                    quality = 10
                elif "postal_town" in result_types:
                    quality = 9
                elif "sublocality" in result_types or "sublocality_level_1" in result_types:
                    quality = 8
                elif "neighborhood" in result_types:
                    quality = 7
                elif "administrative_area_level_3" in result_types:
                    quality = 6
                elif "administrative_area_level_2" in result_types:
                    quality = 5
                elif "postal_code" in result_types:
                    quality = 4
                elif "route" in result_types or "street_address" in result_types:
                    quality = 3
                elif "premise" in result_types or "establishment" in result_types:
                    quality = 2
                elif "point_of_interest" in result_types:
                    quality = 1
                else:
                    quality = 0

                if quality > best_quality:
                    best_quality = quality
                    confidence = (
                        "SETTLEMENT" if quality >= 7
                        else "AREA" if quality >= 4
                        else "PLACE" if quality >= 2
                        else "APPROXIMATE"
                    )
                    best_result = (lat, lon, confidence)
                    print(f"  Found via Places API: {result.get('name', '?')} (score {quality})")
                    if quality >= 8:
                        return best_result

    except (URLError, HTTPError, json.JSONDecodeError) as e:
        print(f"  Places API error for '{query}': {e}")

    if best_result:
        return best_result

    # --- Fallback: Geocoding API (for queries with street numbers) ---
    if re.search(r"\d+", query):
        try:
            geocode_url = (
                "https://maps.googleapis.com/maps/api/geocode/json?"
                + urlencode({"address": query, "key": GOOGLE_MAPS_API_KEY})
            )
            with urlopen(geocode_url, timeout=10) as response:
                data = json.loads(response.read().decode())

            if data.get("status") == "OK" and data.get("results"):
                result = data["results"][0]
                location = result["geometry"]["location"]
                lat = float(location["lat"])
                lon = float(location["lng"])
                location_type = result.get("geometry", {}).get("location_type", "UNKNOWN")
                if -90 <= lat <= 90 and -180 <= lon <= 180:
                    print(f"  Found via Geocoding API: {location_type}")
                    return (lat, lon, location_type)

        except Exception:
            pass

    return None


# ---------------------------------------------------------------------------
# Batch geocoding
# ---------------------------------------------------------------------------


def geocode_dataframe(
    df: pd.DataFrame,
    address_column: str = "address",
    delay: float = 0.1,
    country_hint: Optional[str] = None,
) -> Tuple[gpd.GeoDataFrame, dict]:
    """
    Geocode all addresses in a DataFrame, returning a GeoDataFrame with point geometries.
    P-code resolution is handled separately via resolve_pcodes() per row.

    Parameters:
        df:             DataFrame with an address or coordinate column.
        address_column: Column name containing addresses or coordinate strings.
        delay:          Seconds between Google API calls (skipped for direct coordinates).
        country_hint:   Country name appended to address queries to bias geocoding results.

    Returns (GeoDataFrame with lat/lon/geometry columns added, stats dict).
    """
    latitudes = []
    longitudes = []
    confidences = []
    stats = {
        "total": len(df),
        "successful": 0,
        "failed": 0,
        "skipped": 0,
        "from_coordinates": 0,
        "geocoded": 0,
    }

    print(f"\nProcessing {len(df)} rows...")

    for row_count, (idx, row) in enumerate(df.iterrows(), start=1):
        address = row.get(address_column, "")

        # Direct coordinate parse — no API call needed
        coords = parse_coordinates(address) if address and pd.notna(address) else None
        if coords:
            lat, lon = coords
            latitudes.append(lat)
            longitudes.append(lon)
            confidences.append("COORDINATES")
            stats["successful"] += 1
            stats["from_coordinates"] += 1
            print(f"[{row_count}/{len(df)}] {address}")
            print(f"  --> {lat:.6f}, {lon:.6f} (COORDINATES)")
            continue

        # Build query, optionally prepending name column
        name = row.get("name") if "name" in df.columns else None
        parts = []
        if name is not None and pd.notna(name) and str(name).strip():
            parts.append(str(name).strip())
        if address is not None and pd.notna(address) and str(address).strip():
            parts.append(str(address).strip())
        full_query = ", ".join(parts)

        if not full_query:
            print(f"[{row_count}/{len(df)}] (empty -- skipped)")
            latitudes.append(None)
            longitudes.append(None)
            confidences.append(None)
            stats["skipped"] += 1
            continue

        print(f"[{row_count}/{len(df)}] {full_query}")
        try:
            coords = geocode_address(full_query, country_hint)
            if coords:
                lat, lon, confidence = coords
                latitudes.append(lat)
                longitudes.append(lon)
                confidences.append(confidence)
                stats["successful"] += 1
                stats["geocoded"] += 1
                print(f"  --> {lat:.6f}, {lon:.6f} ({confidence})")
            else:
                latitudes.append(None)
                longitudes.append(None)
                confidences.append(None)
                stats["failed"] += 1
                print("  --> Failed to geocode")
        except Exception as e:
            print(f"  --> Error: {e}")
            latitudes.append(None)
            longitudes.append(None)
            confidences.append(None)
            stats["failed"] += 1

        if row_count < len(df):
            time.sleep(delay)

    df = df.copy()
    df["latitude"] = latitudes
    df["longitude"] = longitudes
    df["geocode_confidence"] = confidences

    geometry = [
        Point(lon, lat) if lat is not None and lon is not None else None
        for lat, lon in zip(latitudes, longitudes)
    ]
    gdf = gpd.GeoDataFrame(df, geometry=geometry, crs="EPSG:4326")
    return gdf, stats
