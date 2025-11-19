#!/usr/bin/env python3
"""
Geocode addresses and match to Jamaica administrative boundaries using GeoPandas.
Uses Google Maps Geocoding API for accurate geocoding.
"""

import os
import time
import json
import re
from pathlib import Path
from typing import Optional, Tuple, Union
from urllib.parse import urlencode
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

import pandas as pd
import geopandas as gpd
from shapely.geometry import Point
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Google Maps API key (loaded from .env file)
GOOGLE_MAPS_API_KEY = os.getenv('GOOGLE_MAPS_API_KEY', '')


def parse_coordinates(text: str) -> Optional[Tuple[float, float]]:
    """
    Try to parse coordinates from a text string.
    Supports formats like:
    - "18.1234, -77.5678"
    - "18.1234,-77.5678"
    - "18.1234 -77.5678"
    - "(18.1234, -77.5678)"
    
    Returns (latitude, longitude) or None if not valid coordinates.
    """
    if not text or pd.isna(text):
        return None
    
    text = str(text).strip()
    
    # Remove parentheses if present
    text = text.strip('()')
    
    # Try to match coordinate patterns
    # Pattern: optional minus, digits, optional decimal point and digits, whitespace/comma, repeat
    coord_pattern = r'^(-?\d+\.?\d*)\s*[,\s]\s*(-?\d+\.?\d*)$'
    match = re.match(coord_pattern, text)
    
    if match:
        try:
            lat = float(match.group(1))
            lon = float(match.group(2))
            
            # Validate Jamaica coordinates (roughly 17-19°N, 76-79°W)
            # Accept both positive/negative longitude formats
            if 17.0 <= lat <= 19.0:
                # Normalize longitude to negative (West)
                if lon > 0:
                    lon = -lon
                if -79.0 <= lon <= -76.0:
                    return (lat, lon)
            
            # Also check if lat/lon are swapped
            if 17.0 <= lon <= 19.0:
                if lat > 0:
                    lat = -lat
                if -79.0 <= lat <= -76.0:
                    return (lon, lat)  # Return swapped
        except ValueError:
            pass
    
    return None


def geocode_address(full_address: str) -> Optional[Tuple[float, float, str]]:
    """
    Geocode a full address query string using Google Maps Geocoding API.
    The caller should include any contextual fields (e.g. name) in the query.
    Returns (latitude, longitude, confidence) or None if not found.
    Confidence is the location_type from Google: ROOFTOP, RANGE_INTERPOLATED, GEOMETRIC_CENTER, or APPROXIMATE.
    
    If the address is already in coordinate format (lat, lon), returns those coordinates
    with confidence 'COORDINATES'.
    """
    # First check if the address is already coordinates
    coords = parse_coordinates(full_address)
    if coords:
        lat, lon = coords
        return (lat, lon, 'COORDINATES')
    
    if not GOOGLE_MAPS_API_KEY:
        print("Error: GOOGLE_MAPS_API_KEY not set. Please set it in your .env or environment.")
        return None

    # Ensure Jamaica is present to bias results
    query = full_address.strip()
    if 'jamaica' not in query.lower():
        query = f"{query}, Jamaica"

    params = {
        'address': query,
        'key': GOOGLE_MAPS_API_KEY,
        'region': 'jm',  # Bias results to Jamaica
        'components': 'country:JM'  # Restrict results to Jamaica only
    }

    url = f"https://maps.googleapis.com/maps/api/geocode/json?{urlencode(params)}"

    try:
        with urlopen(url, timeout=10) as response:
            data = json.loads(response.read().decode())

            status = data.get('status')
            if status == 'OK' and data.get('results'):
                result = data['results'][0]
                location = result['geometry']['location']
                geometry = result.get('geometry', {})
                location_type = geometry.get('location_type', 'UNKNOWN')
                
                # Verify the result is in Jamaica by checking country component
                address_components = result.get('address_components', [])
                is_jamaica = any(
                    'country' in comp.get('types', []) and comp.get('short_name') == 'JM'
                    for comp in address_components
                )
                
                if not is_jamaica:
                    print(f"  Result outside Jamaica, skipping")
                    return None
                
                # Check if result has meaningful address components beyond just country
                # We want at least a locality or administrative area
                has_specific_location = any(
                    any(t in comp.get('types', []) for t in ['locality', 'administrative_area_level_1', 
                                                               'administrative_area_level_2', 'postal_code',
                                                               'route', 'street_address', 'premise'])
                    for comp in address_components
                )
                
                if not has_specific_location:
                    print(f"  Result lacks specific location details, rejecting")
                    return None
                
                lat = float(location['lat'])
                lon = float(location['lng'])
                
                # Additional check: Jamaica coordinates are roughly 17-19°N, 76-79°W
                if not (17.0 <= lat <= 19.0 and -79.0 <= lon <= -76.0):
                    print(f"  Coordinates outside Jamaica bounds, skipping")
                    return None
                
                return (lat, lon, location_type)
            elif status == 'ZERO_RESULTS':
                return None
            else:
                print(f"  API returned status: {status}")
                return None

    except (URLError, HTTPError, json.JSONDecodeError) as e:
        print(f"  Error geocoding '{full_address}': {e}")
        return None
    except Exception as e:
        print(f"  Unexpected error geocoding '{full_address}': {e}")
        return None


def geocode_dataframe(df: pd.DataFrame, address_column: str = 'address', delay: float = 0.1) -> Tuple[gpd.GeoDataFrame, dict]:
    """
    Geocode all addresses in a DataFrame and return a GeoDataFrame with statistics.
    
    Parameters:
    - df: Input DataFrame with addresses
    - address_column: Name of column containing addresses
    - delay: Delay between requests in seconds (Google allows ~50 req/sec, 0.1s is safe)
    
    Returns:
    - Tuple of (GeoDataFrame with point geometries, statistics dict)
    """
    latitudes = []
    longitudes = []
    confidences = []
    stats = {'total': len(df), 'successful': 0, 'failed': 0, 'skipped': 0}
    
    print(f"\nGeocoding {len(df)} addresses...")
    
    row_count = 0
    for idx, row in df.iterrows():
        row_count += 1
        address = row.get(address_column, '')
        
        # Check if address is coordinates first
        coords_from_address = parse_coordinates(address) if address and pd.notna(address) else None
        
        if coords_from_address:
            # Address is already coordinates, use directly
            lat, lon = coords_from_address
            latitudes.append(lat)
            longitudes.append(lon)
            confidences.append('COORDINATES')
            stats['successful'] += 1
            print(f"[{row_count}/{len(df)}] {address}")
            print(f"  → {lat:.6f}, {lon:.6f} (COORDINATES)")
            
            # Still respect rate limit for consistency
            if row_count < len(df):
                time.sleep(delay)
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
            coords = geocode_address(full_query)
            
            if coords:
                lat, lon, confidence = coords
                latitudes.append(lat)
                longitudes.append(lon)
                confidences.append(confidence)
                stats['successful'] += 1
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
    limit: Optional[int] = None
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
    """
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
    points_gdf, stats = geocode_dataframe(df, address_column, delay)
    
    # Print statistics
    print(f"\nGeocoding Statistics:")
    print(f"  Total addresses: {stats['total']}")
    print(f"  Successfully geocoded: {stats['successful']}")
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
        print("GeoPandas-based Address Geocoder and Boundary Matcher")
        print("="*60)
        print("\nUsage: python geocode.py <address_csv> <boundaries_geojson> [output_file] [--limit N]")
        print("\nExamples:")
        print("  # Create .env file with your API key")
        print("  echo 'GOOGLE_MAPS_API_KEY=your-api-key-here' > .env")
        print("  python geocode.py addresses.csv communities.geojson output.csv")
        print("\n  # Test with first 10 addresses")
        print("  python geocode.py addresses.csv communities.geojson output.xlsx --limit 10")
        print("\n  # Output as GeoJSON")
        print("  python geocode.py addresses.csv communities.geojson output.geojson")
        print("\nThe CSV should have a column named 'address' with street addresses.")
        print("\nRequired: Google Maps API key in .env file (GOOGLE_MAPS_API_KEY=your-key)")
        print("Get your API key at: https://console.cloud.google.com/google/maps-apis")
        print("\nRequired packages: pandas, geopandas, shapely, python-dotenv")
        sys.exit(1)
    
    # Parse arguments
    args = sys.argv[1:]
    limit = None
    
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
        limit=limit
    )


if __name__ == "__main__":
    main()
