#!/usr/bin/env python3
"""
Humanitarian Geocoder - Geocode addresses and match to administrative boundaries.
Supports multiple countries for humanitarian response efforts.

Features:
- Accepts both street addresses AND coordinates (lat, lon) in the address column
- Street addresses are geocoded using Google Maps Geocoding API
- Coordinates are used directly without API calls
- All results are spatially joined to administrative boundaries for P-code assignment

Input formats supported:
- Street address: "123 Main St, Kingston, Jamaica"
- Coordinates: "18.1234, -77.5678" or "18,1234 -77,5678" (period or comma as decimal separator)
- Coordinates variations: "(18.1234, -77.5678)" or "18.1234 -77.5678"
- Mixed files: Some rows with addresses, some with coordinates
"""

import os
import time
import json
import re
from pathlib import Path
from typing import Optional, Tuple, Union, Dict, Any
from urllib.parse import urlencode
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

import pandas as pd
import geopandas as gpd
from shapely.geometry import Point
from dotenv import load_dotenv

from countries.country_config import get_country_config, validate_coordinates, normalize_longitude, DEFAULT_COUNTRY

# Load environment variables from .env file
load_dotenv()

# Google Maps API key (loaded from .env file)
GOOGLE_MAPS_API_KEY = os.getenv('GOOGLE_MAPS_API_KEY', '')

# Settlement types for Places API - prioritizes populated places over other features
SETTLEMENT_TYPES = [
    'locality',           # Cities, towns, villages
    'sublocality',        # Neighborhoods within cities
    'postal_town',        # Postal towns
    'neighborhood',       # Named neighborhoods
    'administrative_area_level_3'  # Small administrative areas (often communities/towns)
]


def parse_coordinates(text: str, country_config: Optional[Dict[str, Any]] = None) -> Optional[Tuple[float, float]]:
    """
    Try to parse coordinates from a text string.
    Supports formats like:
    - "18.1234, -77.5678" or "18,1234 -77,5678" (period or comma as decimal separator)
    - "18.1234,-77.5678"
    - "18.1234 -77.5678"
    - "(18.1234, -77.5678)"
    
    Parameters:
    - text: String potentially containing coordinates
    - country_config: Country configuration dictionary (optional, for validation)
    
    Returns (latitude, longitude) or None if not valid coordinates.
    """
    if not text or pd.isna(text):
        return None
    
    if country_config is None:
        country_config = get_country_config(DEFAULT_COUNTRY)
    
    text = str(text).strip()
    
    # Remove parentheses if present
    text = text.strip('()')
    
    # Replace commas used as decimal separators with periods
    # We need to distinguish between commas as separators vs decimal points
    # Strategy: if we have exactly 2 numbers separated by space or comma/space,
    # then any other commas are likely decimal separators
    
    # Try to match coordinate patterns (allowing comma or period as decimal separator)
    # Pattern: optional minus, digits, optional decimal point/comma and digits, whitespace/comma, repeat
    coord_pattern = r'^(-?\d+[.,]?\d*)\s*[,\s]\s*(-?\d+[.,]?\d*)$'
    match = re.match(coord_pattern, text)
    
    if match:
        try:
            # Get the two coordinate strings and replace commas with periods for float parsing
            lat_str = match.group(1).replace(',', '.')
            lon_str = match.group(2).replace(',', '.')
            
            lat = float(lat_str)
            lon = float(lon_str)
            
            # Normalize longitude sign based on country hemisphere
            lon = normalize_longitude(lon, country_config)
            
            # Validate coordinates against country bounds
            if validate_coordinates(lat, lon, country_config):
                return (lat, lon)
            
            # Also check if lat/lon are swapped
            lat_swapped = lon
            lon_swapped = normalize_longitude(lat, country_config)
            if validate_coordinates(lat_swapped, lon_swapped, country_config):
                return (lat_swapped, lon_swapped)  # Return swapped
        except ValueError:
            pass
    
    return None


def geocode_address(full_address: str, country_config: Optional[Dict[str, Any]] = None) -> Optional[Tuple[float, float, str]]:
    """
    Geocode a full address query string using Google Maps Geocoding API.
    The caller should include any contextual fields (e.g. name) in the query.
    
    Parameters:
    - full_address: Address string to geocode OR coordinate string (e.g., "18.123, -77.456")
    - country_config: Country configuration dictionary (optional, defaults to Jamaica)
    
    Returns (latitude, longitude, confidence) or None if not found.
    Confidence is the location_type from Google: ROOFTOP, RANGE_INTERPOLATED, GEOMETRIC_CENTER, APPROXIMATE,
    or COORDINATES (if the input was already in coordinate format).
    
    If the address is already in coordinate format (lat, lon), returns those coordinates
    with confidence 'COORDINATES' WITHOUT making an API call.
    
    For addresses: Uses multiple fallback strategies to find approximate locations for vague addresses.
    """
    if country_config is None:
        country_config = get_country_config(DEFAULT_COUNTRY)
    
    # First check if the address is already coordinates
    coords = parse_coordinates(full_address, country_config)
    if coords:
        lat, lon = coords
        return (lat, lon, 'COORDINATES')
    
    if not GOOGLE_MAPS_API_KEY:
        print("Error: GOOGLE_MAPS_API_KEY not set. Please set it in your .env or environment.")
        return None

    # Ensure country name is present to bias results
    country_name = country_config['name']
    query = full_address.strip()
    if country_name.lower() not in query.lower():
        query = f"{query}, {country_name}"
    
    # Apply country-specific spelling corrections
    spelling_corrections = country_config.get('spelling_corrections', {})
    query_lower = query.lower()
    for typo, correction in spelling_corrections.items():
        if typo in query_lower:
            query = query_lower.replace(typo, correction) + f', {country_name}'
            break

    # Try different query strategies in order of preference
    queries_to_try = [
        query,  # Original query (possibly corrected)
    ]
    
    # For vague addresses, try adding common modifiers (if fallback parishes available)
    fallback_locations = country_config.get('fallback_parishes', [])
    if fallback_locations and any(word in query.lower() for word in ['orphanage', 'home', 'school', 'church', 'castle', 'outskirts']):
        # Try without country name to see if it's a known place
        base = query.replace(f', {country_name}', '').replace(f',{country_name}', '').strip()
        for location in fallback_locations[:3]:  # Try first 3 fallback locations
            queries_to_try.append(f"{base}, {location}, {country_name}")
    
    best_result = None
    best_quality = -1  # Track quality: Higher values = better
    
    # PRIMARY APPROACH: Google Places API with settlement type filtering
    # This biases results toward populated places (towns, cities, neighborhoods) over
    # random features like roads, establishments, or points of interest when there are
    # multiple places with the same name in a country.
    for attempt_query in queries_to_try:
        try:
            # Build location restriction to country bounds for better filtering
            bounds = country_config.get('bounds')
            location_bias = ''
            if bounds:
                # Use rectangular bounds for location biasing
                lat_min = bounds['lat_min']
                lat_max = bounds['lat_max']
                lon_min = bounds['lon_min']
                lon_max = bounds['lon_max']
                location_bias = f"&locationbias=rectangle:{lat_min},{lon_min}|{lat_max},{lon_max}"
            
            places_params = {
                'query': attempt_query,
                'key': GOOGLE_MAPS_API_KEY,
                'region': country_config['google_maps_region'],
            }
            
            places_url = f"https://maps.googleapis.com/maps/api/place/textsearch/json?{urlencode(places_params)}{location_bias}"
            
            with urlopen(places_url, timeout=10) as response:
                data = json.loads(response.read().decode())
                
                if data.get('status') == 'OK' and data.get('results'):
                    # Process all results and score by settlement type priority
                    for result in data['results']:
                        result_types = set(result.get('types', []))
                        
                        # Verify result is within country bounds
                        location = result['geometry']['location']
                        lat = float(location['lat'])
                        lon = float(location['lng'])
                        
                        if not validate_coordinates(lat, lon, country_config):
                            continue
                        
                        # Score based on settlement type hierarchy
                        # Higher score = more likely to be a settlement rather than a random feature
                        quality = 0
                        
                        # Primary settlement types (highest priority)
                        if 'locality' in result_types:  # Cities, towns, villages
                            quality = 10
                        elif 'postal_town' in result_types:
                            quality = 9
                        elif 'sublocality' in result_types or 'sublocality_level_1' in result_types:
                            quality = 8
                        elif 'neighborhood' in result_types:
                            quality = 7
                        elif 'administrative_area_level_3' in result_types:  # Small admin areas
                            quality = 6
                        elif 'administrative_area_level_2' in result_types:  # Districts
                            quality = 5
                        # Secondary types (lower priority)
                        elif 'postal_code' in result_types:
                            quality = 4
                        elif 'route' in result_types or 'street_address' in result_types:
                            quality = 3
                        elif 'premise' in result_types or 'establishment' in result_types:
                            quality = 2
                        elif 'point_of_interest' in result_types:
                            quality = 1
                        else:
                            quality = 0  # Unknown or too generic
                        
                        # Update best result if this is better
                        if quality > best_quality:
                            best_quality = quality
                            
                            # Create descriptive confidence string
                            if quality >= 7:
                                confidence = 'SETTLEMENT'  # High confidence settlement
                            elif quality >= 4:
                                confidence = 'AREA'  # Administrative area or postal code
                            elif quality >= 2:
                                confidence = 'PLACE'  # Specific place/address
                            else:
                                confidence = 'APPROXIMATE'  # Generic result
                            
                            best_result = (lat, lon, confidence)
                            place_name = result.get('name', 'Unknown')
                            print(f"  Found via Places API: {place_name} (types: {', '.join(list(result_types)[:3])}...)")
                            
                            # If we found a high-quality settlement, stop searching
                            if quality >= 8:
                                return best_result
        
        except (URLError, HTTPError, json.JSONDecodeError) as e:
            print(f"  Error with Places API for '{attempt_query}': {e}")
            continue
        except Exception as e:
            print(f"  Unexpected error with Places API for '{attempt_query}': {e}")
            continue
    
    # Return best result if found
    if best_result:
        return best_result
    
    # FALLBACK: Try Geocoding API for precise addresses (street addresses with numbers)
    # Only use this for queries that look like specific street addresses
    if re.search(r'\d+', query):  # Has numbers, might be a street address
        try:
            params = {
                'address': query,
                'key': GOOGLE_MAPS_API_KEY,
                'region': country_config['google_maps_region'],
                'components': country_config['google_maps_components']
            }

            url = f"https://maps.googleapis.com/maps/api/geocode/json?{urlencode(params)}"

            with urlopen(url, timeout=10) as response:
                data = json.loads(response.read().decode())

                if data.get('status') == 'OK' and data.get('results'):
                    result = data['results'][0]
                    location = result['geometry']['location']
                    geometry = result.get('geometry', {})
                    location_type = geometry.get('location_type', 'UNKNOWN')
                    
                    # Verify the result is in the correct country
                    address_components = result.get('address_components', [])
                    is_correct_country = any(
                        'country' in comp.get('types', []) and comp.get('short_name') == country_config['code']
                        for comp in address_components
                    )
                    
                    if is_correct_country:
                        lat = float(location['lat'])
                        lon = float(location['lng'])
                        
                        # Validate coordinates against country bounds
                        if validate_coordinates(lat, lon, country_config):
                            print(f"  Found via Geocoding API: {location_type}")
                            return (lat, lon, location_type)
        
        except Exception as e:
            pass  # Silently fail Geocoding API fallback
    
    return None


def geocode_dataframe(df: pd.DataFrame, address_column: str = 'address', delay: float = 0.1, 
                     country_config: Optional[Dict[str, Any]] = None) -> Tuple[gpd.GeoDataFrame, dict]:
    """
    Geocode all addresses in a DataFrame and return a GeoDataFrame with statistics.
    Accepts both street addresses (geocoded via API) and coordinates (used directly).
    
    Parameters:
    - df: Input DataFrame with addresses or coordinates
    - address_column: Name of column containing addresses or coordinates (lat, lon format)
    - delay: Delay between API requests in seconds (Google allows about 50 req/sec, 0.1s is safe)
             No delay applied for coordinate rows.
    - country_config: Country configuration dictionary (optional, defaults to Jamaica)
    
    Returns:
    - Tuple of (GeoDataFrame with point geometries, statistics dict)
    
    The address column can contain:
    - Street addresses: "123 Main St, Kingston" -> geocoded via Google Maps API
    - Coordinates: "18.1234, -77.5678" -> used directly without API call
    - Mixed: Some rows with addresses, some with coordinates
    
    All results (geocoded or coordinates) are spatially joined to admin boundaries.
    """
    if country_config is None:
        country_config = get_country_config(DEFAULT_COUNTRY)
    
    latitudes = []
    longitudes = []
    confidences = []
    stats = {'total': len(df), 'successful': 0, 'failed': 0, 'skipped': 0, 'from_coordinates': 0, 'geocoded': 0}
    
    print(f"\nProcessing {len(df)} addresses/coordinates for {country_config['name']}...")
    
    row_count = 0
    for idx, row in df.iterrows():
        row_count += 1
        address = row.get(address_column, '')
        
        # Check if address is coordinates first
        coords_from_address = parse_coordinates(address, country_config) if address and pd.notna(address) else None
        
        if coords_from_address:
            # Address is already coordinates, use directly (no API call needed)
            lat, lon = coords_from_address
            latitudes.append(lat)
            longitudes.append(lon)
            confidences.append('COORDINATES')
            stats['successful'] += 1
            stats['from_coordinates'] += 1
            print(f"[{row_count}/{len(df)}] {address}")
            print(f"  → {lat:.6f}, {lon:.6f} (COORDINATES - no API call)")
            # No delay needed since no API call was made
            continue
        
        # If the CSV has a 'name' column, include it in the query to improve matching
        name = row.get('name') if 'name' in df.columns else None
        parts = []
        if name is not None and pd.notna(name) and str(name).strip():
            parts.append(str(name).strip())
        if address is not None and pd.notna(address) and str(address).strip():
            parts.append(str(address).strip())
        full_query = ", ".join(parts) if parts else ''

        # Skip empty addresses
        if not full_query:
            print(f"[{row_count}/{len(df)}] (empty address - skipped)")
            latitudes.append(None)
            longitudes.append(None)
            confidences.append(None)
            stats['skipped'] += 1
            continue

        print(f"[{row_count}/{len(df)}] {full_query}")

        try:
            coords = geocode_address(full_query, country_config)
            
            if coords:
                lat, lon, confidence = coords
                latitudes.append(lat)
                longitudes.append(lon)
                confidences.append(confidence)
                stats['successful'] += 1
                stats['geocoded'] += 1
                print(f"  → {lat:.6f}, {lon:.6f} ({confidence})")
            else:
                latitudes.append(None)
                longitudes.append(None)
                confidences.append(None)
                stats['failed'] += 1
                print(f"  → Failed to geocode")
        except Exception as e:
            print(f"  → Error during geocoding: {str(e)}")
            latitudes.append(None)
            longitudes.append(None)
            confidences.append(None)
            stats['failed'] += 1
        
        # Respect API rate limit - only sleep if not the last row
        if row_count < len(df):
            time.sleep(delay)
    
    # Create GeoDataFrame
    df['latitude'] = latitudes
    df['longitude'] = longitudes
    df['geocode_confidence'] = confidences
    
    # Create geometry column (only for successfully geocoded points)
    geometry = [Point(lon, lat) if lat is not None and lon is not None else None 
                for lat, lon in zip(latitudes, longitudes)]
    
    gdf = gpd.GeoDataFrame(df, geometry=geometry, crs="EPSG:4326")
    
    return gdf, stats


def spatial_join_boundaries(points_gdf: gpd.GeoDataFrame, boundaries_gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    Perform spatial join to match points to administrative boundaries.
    Points that don't fall within any boundary are matched to the nearest boundary.
    
    Parameters:
    - points_gdf: GeoDataFrame with geocoded points
    - boundaries_gdf: GeoDataFrame with administrative boundaries
    
    Returns:
    - GeoDataFrame with boundary attributes joined to points
    """
    print("\nPerforming spatial join...")
    
    # Ensure both are in same CRS
    if points_gdf.crs != boundaries_gdf.crs:
        boundaries_gdf = boundaries_gdf.to_crs(points_gdf.crs)
    
    # Remove rows with no geometry (failed geocoding)
    points_with_geom = points_gdf[points_gdf.geometry.notna()].copy()
    points_without_geom = points_gdf[points_gdf.geometry.isna()].copy()
    
    if len(points_with_geom) > 0:
        # Get original column order from points (excluding geometry)
        original_cols = [col for col in points_with_geom.columns if col != 'geometry']
        
        # Spatial join - points within boundaries
        joined = gpd.sjoin(points_with_geom, boundaries_gdf, how='left', predicate='within')
        
        # Drop the spatial index column that sjoin adds
        if 'index_right' in joined.columns:
            joined = joined.drop(columns=['index_right'])
        
        # Find points that didn't match any boundary (null in admin columns)
        # Look for the first boundary column to check
        boundary_cols = [col for col in boundaries_gdf.columns if col != 'geometry']
        if boundary_cols:
            first_boundary_col = boundary_cols[0]
            unmatched_mask = joined[first_boundary_col].isna()
            unmatched_indices = joined[unmatched_mask].index.tolist()
            
            if len(unmatched_indices) > 0:
                print(f"  {len(unmatched_indices)} points outside boundaries, matching to nearest...")
                
                # For each unmatched point, find nearest boundary and create proper rows
                for idx in unmatched_indices:
                    point_geom = joined.loc[idx, 'geometry']
                    if point_geom is not None:
                        # Calculate distance to all boundaries
                        distances = boundaries_gdf.geometry.distance(point_geom)
                        nearest_idx = distances.idxmin()
                        
                        # Copy boundary attributes to the point (update existing row)
                        for col in boundary_cols:
                            if col in boundaries_gdf.columns:
                                joined.loc[idx, col] = boundaries_gdf.loc[nearest_idx, col]
        
        # Combine with points that couldn't be geocoded
        if len(points_without_geom) > 0:
            # Add missing columns to points_without_geom
            for col in joined.columns:
                if col not in points_without_geom.columns:
                    points_without_geom[col] = None
            
            result = pd.concat([joined, points_without_geom], ignore_index=True)
        else:
            result = joined
    else:
        result = points_gdf
    
    return result


def process_addresses(
    address_file: str,
    geojson_file: str,
    output_file: str,
    address_column: str = 'address',
    delay: float = 1.0,
    keep_geometry: bool = False,
    limit: Optional[int] = None,
    country: str = DEFAULT_COUNTRY
):
    """
    Process addresses: geocode and match to administrative boundaries.
    
    Parameters:
    - address_file: Path to CSV file with addresses
    - geojson_file: Path to GeoJSON file with boundaries
    - output_file: Path to output file (CSV or GeoJSON)
    - address_column: Name of column with addresses
    - delay: Delay between geocoding requests (seconds)
    - keep_geometry: If True, output as GeoJSON; if False, output as CSV
    - limit: Optional limit on number of addresses to process (for testing)
    - country: Country code or name (e.g., 'jamaica', 'mozambique', 'JM', 'MZ')
    """
    # Load country configuration
    country_config = get_country_config(country)
    country_name = country_config['name']
    
    print(f"Processing addresses for {country_name}...")
    
    # Read addresses
    print(f"Reading addresses from {address_file}...")
    # Attempt to read as a normal CSV first so existing columns are preserved.
    try:
        df = pd.read_csv(address_file, encoding='utf-8-sig', sep=';')
        print(f"Found {len(df)} rows (preserved CSV columns)")
        
        # Convert date format from m/d to yyyy-mm-dd (assuming current year 2025)
        if 'date' in df.columns:
            def convert_date(date_str):
                if pd.isna(date_str):
                    return date_str
                try:
                    # Parse m/d format and add year
                    parts = str(date_str).strip().split('/')
                    if len(parts) == 2:
                        month, day = parts
                        return f"2025-{int(month):02d}-{int(day):02d}"
                    return date_str
                except:
                    return date_str
            
            df['date'] = df['date'].apply(convert_date)
        
        # If address_column is not present, try to handle single-column CSVs
        if address_column not in df.columns:
            # If the file only had one column without header, treat it as addresses
            if df.shape[1] == 1:
                df.columns = [address_column]
            else:
                print(f"Warning: Column '{address_column}' not found in CSV; available columns: {', '.join(df.columns)}")
    except pd.errors.ParserError:
        # Fall back to simple single-column reading (addresses may contain commas)
        with open(address_file, 'r', encoding='utf-8-sig') as f:
            lines = [line.strip() for line in f.readlines()]

        # First line is the header
        if lines and lines[0].lower().strip() == address_column:
            addresses = [addr for addr in lines[1:] if addr]
        else:
            addresses = [addr for addr in lines if addr]

        df = pd.DataFrame({address_column: addresses})
        print(f"Found {len(df)} addresses (single-column fallback)")
    
    # Apply limit if specified
    if limit is not None and limit > 0:
        df = df.head(limit)
        print(f"Limiting to first {len(df)} addresses")
    
    # Check if address column exists
    if address_column not in df.columns:
        print(f"Error: Column '{address_column}' not found.")
        print(f"Available columns: {', '.join(df.columns)}")
        return
    
    # Read boundaries
    print(f"\nReading boundaries from {geojson_file}...")
    boundaries = gpd.read_file(geojson_file)
    print(f"Loaded {len(boundaries)} boundary features")
    print(f"Boundary CRS: {boundaries.crs}")
    
    # Identify relevant columns from boundaries
    print(f"\nBoundary columns: {', '.join(boundaries.columns)}")
    
    # Geocode addresses
    points_gdf, stats = geocode_dataframe(df, address_column, delay, country_config)
    
    # Print statistics
    print(f"\nProcessing Statistics:")
    print(f"  Total addresses: {stats['total']}")
    print(f"  Successfully processed: {stats['successful']}")
    print(f"    - From coordinates (no API call): {stats['from_coordinates']}")
    print(f"    - Geocoded via API: {stats['geocoded']}")
    print(f"  Failed to geocode: {stats['failed']}")
    print(f"  Skipped (empty): {stats['skipped']}")
    
    # Spatial join
    result = spatial_join_boundaries(points_gdf, boundaries)
    
    # Count successful matches
    # Assuming ADM3_EN is the community name field
    admin_col = None
    for possible_col in ['ADM3_EN', 'admin3_name', 'ADM2_EN', 'admin2_name', 'name']:
        if possible_col in result.columns:
            admin_col = possible_col
            break
    
    if admin_col:
        matched = result[admin_col].notna().sum()
        print(f"Matched to boundaries: {matched}/{len(result)}")
    
    # Save results
    print(f"\nSaving results to {output_file}...")
    
    if keep_geometry or output_file.endswith('.geojson'):
        # Save as GeoJSON
        result.to_file(output_file, driver='GeoJSON')
        print(f"✓ Saved as GeoJSON")
    elif output_file.endswith('.xlsx'):
        # Save as Excel (drop geometry column)
        result_df = pd.DataFrame(result.drop(columns='geometry'))
        result_df.to_excel(output_file, index=False, engine='openpyxl')
        print(f"✓ Saved as Excel")
    else:
        # Save as CSV (drop geometry column)
        result_df = pd.DataFrame(result.drop(columns='geometry'))
        result_df.to_csv(output_file, index=False)
        print(f"✓ Saved as CSV")
    
    # Print summary
    print("\n" + "="*50)
    print("SUMMARY")
    print("="*50)
    print(f"Total addresses: {len(result)}")
    print(f"Successfully geocoded: {successful}")
    if admin_col:
        print(f"Matched to boundaries: {matched}")
    print(f"Output saved to: {output_file}")
    
    # Show sample of results
    if admin_col and matched > 0:
        print(f"\nSample results (showing {admin_col}):")
        sample = result[result[admin_col].notna()].head(5)
        for _, row in sample.iterrows():
            print(f"  {row[address_column]} → {row[admin_col]}")


def main():
    """Main function"""
    import sys
    
    if len(sys.argv) < 3:
        print("Humanitarian Geocoder - Multi-Country Address Geocoding")
        print("="*60)
        print("\nUsage: python geocode.py <address_csv> <boundaries_geojson> [output_file] [OPTIONS]")
        print("\nArguments:")
        print("  address_csv         Input CSV file with addresses")
        print("  boundaries_geojson  GeoJSON file with administrative boundaries")
        print("  output_file         Output filename (default: geocoded_output.csv)")
        print("\nOptions:")
        print("  --limit N           Process only first N addresses")
        print("  --country CODE      Country code (jamaica, mozambique, JM, MZ)")
        print("\nExamples:")
        print("  # Create .env file with your API key")
        print("  echo 'GOOGLE_MAPS_API_KEY=your-api-key-here' > .env")
        print("\n  # Basic usage with custom output filename")
        print("  python geocode.py addresses.csv boundaries/jamaica.geojson results.csv")
        print("\n  # Geocode for Mozambique with custom filename")
        print("  python geocode.py addresses.csv boundaries/mozambique.geojson mozambique_results.xlsx --country mozambique")
        print("\n  # Test with first 10 addresses")
        print("  python geocode.py addresses.csv boundaries/jamaica.geojson test_output.xlsx --limit 10")
        print("\n  # Output as GeoJSON")
        print("  python geocode.py addresses.csv boundaries/jamaica.geojson output.geojson")
        print("\nThe CSV should have a column named 'address' with street addresses or coordinates.")
        print("Coordinates can use period (18.123, -77.456) or comma (18,123 -77,456) as decimal separator.")
        print("\nRequired: Google Maps API key in .env file (GOOGLE_MAPS_API_KEY=your-key)")
        print("Get your API key at: https://console.cloud.google.com/google/maps-apis")
        print("\nSupported countries: jamaica (JM), mozambique (MZ)")
        print("\nRequired packages: pandas, geopandas, shapely, python-dotenv")
        sys.exit(1)
    
    # Parse arguments
    args = sys.argv[1:]
    limit = None
    country = DEFAULT_COUNTRY
    
    # Check for --limit flag
    if '--limit' in args:
        limit_idx = args.index('--limit')
        if limit_idx + 1 < len(args):
            try:
                limit = int(args[limit_idx + 1])
                # Remove --limit and its value from args
                args.pop(limit_idx)
                args.pop(limit_idx)
            except (ValueError, IndexError):
                print("Error: --limit requires a numeric value")
                sys.exit(1)
    
    # Check for --country flag
    if '--country' in args:
        country_idx = args.index('--country')
        if country_idx + 1 < len(args):
            country = args[country_idx + 1]
            # Remove --country and its value from args
            args.pop(country_idx)
            args.pop(country_idx)
        else:
            print("Error: --country requires a value (e.g., jamaica, mozambique, JM, MZ)")
            sys.exit(1)
    
    address_file = args[0]
    geojson_file = args[1]
    output_file = args[2] if len(args) > 2 else 'geocoded_output.csv'
    
    # Check if files exist
    if not Path(address_file).exists():
        print(f"Error: Address file '{address_file}' not found.")
        sys.exit(1)
    
    if not Path(geojson_file).exists():
        print(f"Error: GeoJSON file '{geojson_file}' not found.")
        sys.exit(1)
    
    process_addresses(
        address_file=address_file,
        geojson_file=geojson_file,
        output_file=output_file,
        address_column='address',  # Change if your column has different name
        delay=0.1,  # Google Maps allows ~50 requests/second, 0.1s is conservative
        limit=limit,
        country=country
    )


if __name__ == "__main__":
    main()
