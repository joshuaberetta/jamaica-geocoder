#!/usr/bin/env python3
"""
Humanitarian Geocoder - Web interface for multi-country address geocoding.
Upload CSV, get geocoded results with admin boundaries for humanitarian response.
"""

from flask import Flask, render_template, request, send_file, jsonify, redirect, url_for, session, make_response
from flask_cors import CORS
from werkzeug.utils import secure_filename
import os
import io
import json
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point
from pathlib import Path
import tempfile
from dotenv import load_dotenv
from functools import wraps
import hashlib

# Import geocoding functions from geocode.py
from geocode import geocode_address, geocode_dataframe, spatial_join_boundaries
from countries.country_config import get_country_config, get_all_countries, DEFAULT_COUNTRY

load_dotenv()

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.config['UPLOAD_FOLDER'] = tempfile.gettempdir()
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')

# Login credentials from environment variables
USERNAME = os.getenv('LOGIN_USERNAME', 'admin')
PASSWORD = os.getenv('LOGIN_PASSWORD', 'admin')

# Login required decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Load boundaries once at startup - support multiple countries
boundaries_cache = {}  # Dictionary: country_code -> gdf
boundaries_geojson_cache = {}  # Dictionary: country_code -> geojson string
boundaries_etag_cache = {}  # Dictionary: country_code -> etag

def load_boundaries(country: str = DEFAULT_COUNTRY):
    """
    Load boundaries for a specific country.
    
    Parameters:
    - country: Country code or name (e.g., 'jamaica', 'mozambique', 'JM', 'MZ')
    
    Returns:
    - GeoDataFrame with boundaries or None if not found
    """
    global boundaries_cache, boundaries_geojson_cache, boundaries_etag_cache
    
    try:
        country_config = get_country_config(country)
        country_code = country_config['code']
        
        # Check if already loaded
        if country_code in boundaries_cache:
            return boundaries_cache[country_code]
        
        boundary_file = country_config['boundary_file']
        
        if not Path(boundary_file).exists():
            print(f"Warning: Boundary file not found: {boundary_file}")
            return None
        
        print(f"Loading boundaries for {country_config['name']} from {boundary_file}...")
        gdf = gpd.read_file(boundary_file)
        print(f"Loaded {len(gdf)} boundary features for {country_config['name']}")
        
        # Convert datetime columns to string to avoid JSON serialization errors
        for col in gdf.columns:
            if pd.api.types.is_datetime64_any_dtype(gdf[col]):
                gdf[col] = gdf[col].astype(str)
        
        # Cache the GeoDataFrame
        boundaries_cache[country_code] = gdf
        
        # Pre-compute GeoJSON and ETag for caching
        gdf_wgs84 = gdf.to_crs('EPSG:4326') if gdf.crs and gdf.crs != 'EPSG:4326' else gdf
        geojson_str = gdf_wgs84.to_json()
        etag = hashlib.md5(geojson_str.encode()).hexdigest()
        
        boundaries_geojson_cache[country_code] = geojson_str
        boundaries_etag_cache[country_code] = etag
        
        print(f"Cached boundaries GeoJSON for {country_config['name']} (ETag: {etag})")
        
        return gdf
    except Exception as e:
        print(f"Error loading boundaries for {country}: {e}")
        return None

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if username == USERNAME and password == PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('index'))
        else:
            return render_template('login.html', error='Invalid username or password')
    
    # If already logged in, redirect to main page
    if session.get('logged_in'):
        return redirect(url_for('index'))
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('index'))

@app.route('/')
def index():
    # Get list of available countries
    countries = get_all_countries()
    return render_template('index.html', logged_in=session.get('logged_in', False), countries=countries)

@app.route('/geocode', methods=['POST'])
@login_required
def geocode():
    try:
        # Get country parameter (default to jamaica for backward compatibility)
        country = request.form.get('country', DEFAULT_COUNTRY)
        country_config = get_country_config(country)
        
        # Check if this is a single address request
        if request.is_json or request.form.get('single_address'):
            return geocode_single()
        
        # Check if file was uploaded
        if 'file' not in request.files:
            return jsonify({'error': 'No file uploaded'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        # Get limit parameter if provided
        limit = request.form.get('limit', type=int)
        
        # Read the CSV file
        try:
            # Check file extension to determine how to read it
            filename = secure_filename(file.filename)
            if filename.endswith('.xlsx') or filename.endswith('.xls'):
                df = pd.read_excel(file, engine='openpyxl')
            else:
                # Try CSV with semicolon separator
                df = pd.read_csv(file, encoding='utf-8-sig', sep=';')
            
            # Convert date format from m/d to yyyy-mm-dd
            if 'date' in df.columns:
                def convert_date(date_str):
                    if pd.isna(date_str):
                        return date_str
                    try:
                        parts = str(date_str).strip().split('/')
                        if len(parts) == 2:
                            month, day = parts
                            return f"2025-{int(month):02d}-{int(day):02d}"
                        return date_str
                    except:
                        return date_str
                
                df['date'] = df['date'].apply(convert_date)
            
            # Apply limit if specified
            if limit and limit > 0:
                df = df.head(limit)
            
            if 'address' not in df.columns:
                return jsonify({'error': 'File must have an "address" column'}), 400
            
        except Exception as e:
            return jsonify({'error': f'Failed to read file: {str(e)}'}), 400
        
        # Load boundaries for the selected country
        boundaries = load_boundaries(country)
        if boundaries is None:
            return jsonify({'error': f'Boundary data not available for {country_config["name"]}'}), 500
        
        # Geocode addresses - use minimal delay to avoid timeout
        points_gdf, stats = geocode_dataframe(df, address_column='address', delay=0.05, country_config=country_config)
        
        # Spatial join with boundaries
        result = spatial_join_boundaries(points_gdf, boundaries)
        
        # Convert to DataFrame and prepare for download
        result_df = pd.DataFrame(result.drop(columns='geometry'))
        
        # Create output file
        output = io.BytesIO()
        
        # Check requested format
        output_format = request.form.get('format', 'csv')
        
        if output_format == 'xlsx':
            result_df.to_excel(output, index=False, engine='openpyxl')
            output.seek(0)
            mimetype = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            filename = 'geocoded_addresses.xlsx'
        else:
            result_df.to_csv(output, index=False)
            output.seek(0)
            mimetype = 'text/csv'
            filename = 'geocoded_addresses.csv'
        
        # Encode file as base64 to send with JSON
        import base64
        output.seek(0)
        file_data = base64.b64encode(output.read()).decode('utf-8')
        
        return jsonify({
            'success': True,
            'stats': stats,
            'file_data': file_data,
            'filename': filename,
            'mimetype': mimetype
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/geocode_single', methods=['POST'])
def geocode_single():
    """Geocode a single address or GPS coordinate (public endpoint)."""
    try:
        data = request.get_json() if request.is_json else request.form
        address_input = data.get('address', '').strip()
        country = data.get('country', DEFAULT_COUNTRY)
        
        if not address_input:
            return jsonify({'error': 'Address or GPS coordinates required'}), 400
        
        # Get country configuration
        country_config = get_country_config(country)
        
        # Load boundaries for the selected country
        boundaries = load_boundaries(country)
        if boundaries is None:
            return jsonify({'error': f'Boundary data not available for {country_config["name"]}'}), 500
        
        # Geocode the address
        result = geocode_address(address_input, country_config)
        
        if result is None:
            return jsonify({
                'success': False,
                'error': 'Could not geocode the address',
                'address': address_input
            })
        
        lat, lon, confidence = result
        
        # Create a point and find which boundaries it falls in
        point = Point(lon, lat)
        point_gdf = gpd.GeoDataFrame(
            {'address': [address_input], 'latitude': [lat], 'longitude': [lon], 'confidence': [confidence]},
            geometry=[point],
            crs='EPSG:4326'
        )
        
        # Perform spatial join
        joined = spatial_join_boundaries(point_gdf, boundaries)
        
        # Extract the result - use admin level fields from country config
        if len(joined) > 0:
            row = joined.iloc[0]
            admin_levels = country_config['admin_levels']
            
            response_data = {
                'success': True,
                'address': address_input,
                'latitude': lat,
                'longitude': lon,
                'confidence': confidence,
                'admin1_pcode': row.get(admin_levels['level1']['pcode_field']),
                'admin1_name': row.get(admin_levels['level1']['name_field']),
                'admin1_label': admin_levels['level1']['label'],
                'admin2_pcode': row.get(admin_levels['level2']['pcode_field']),
                'admin2_name': row.get(admin_levels['level2']['name_field']),
                'admin2_label': admin_levels['level2']['label'],
                'country': country_config['name'],
                'country_code': country_config['code']
            }
            return jsonify(response_data)
        else:
            return jsonify({
                'success': False,
                'error': 'Could not match to administrative boundaries',
                'address': address_input,
                'latitude': lat,
                'longitude': lon,
                'confidence': confidence
            })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/boundaries.geojson')
def get_boundaries():
    """Serve the boundaries GeoJSON file reprojected to WGS84 (public endpoint) with caching."""
    try:
        # Get country parameter (default to jamaica)
        country = request.args.get('country', DEFAULT_COUNTRY)
        
        # Load boundaries if not already loaded
        load_boundaries(country)
        
        country_config = get_country_config(country)
        country_code = country_config['code']
        
        if country_code not in boundaries_geojson_cache:
            return jsonify({'error': f'Boundary file not found for {country_config["name"]}'}), 404
        
        # Check if client has cached version (ETag)
        client_etag = request.headers.get('If-None-Match')
        server_etag = boundaries_etag_cache.get(country_code)
        
        if client_etag and server_etag and client_etag == f'"{server_etag}"':
            return '', 304  # Not Modified
        
        # Create response with caching headers
        response = make_response(boundaries_geojson_cache[country_code])
        response.headers['Content-Type'] = 'application/json'
        response.headers['ETag'] = f'"{server_etag}"'
        response.headers['Cache-Control'] = 'public, max-age=86400'  # Cache for 24 hours
        
        return response
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/reverse_geocode', methods=['POST'])
def reverse_geocode():
    """Get pcode information for a lat/lon coordinate (public endpoint)."""
    try:
        data = request.get_json() if request.is_json else request.form
        lat = data.get('latitude') or data.get('lat')
        lon = data.get('longitude') or data.get('lon')
        country = data.get('country', DEFAULT_COUNTRY)
        
        if lat is None or lon is None:
            return jsonify({'error': 'Latitude and longitude required'}), 400
        
        try:
            lat = float(lat)
            lon = float(lon)
        except ValueError:
            return jsonify({'error': 'Invalid latitude or longitude format'}), 400
        
        # Get country configuration
        country_config = get_country_config(country)
        
        # Load boundaries for the selected country
        boundaries = load_boundaries(country)
        if boundaries is None:
            return jsonify({'error': f'Boundary data not available for {country_config["name"]}'}), 500
        
        # Create a point from the coordinates
        point = Point(lon, lat)
        point_gdf = gpd.GeoDataFrame(
            {'latitude': [lat], 'longitude': [lon]},
            geometry=[point],
            crs='EPSG:4326'
        )
        
        # Perform spatial join
        joined = spatial_join_boundaries(point_gdf, boundaries)
        
        # Extract the result - use admin level fields from country config
        if len(joined) > 0:
            row = joined.iloc[0]
            admin_levels = country_config['admin_levels']
            
            response_data = {
                'success': True,
                'latitude': lat,
                'longitude': lon,
                'admin1_pcode': row.get(admin_levels['level1']['pcode_field']),
                'admin1_name': row.get(admin_levels['level1']['name_field']),
                'admin1_label': admin_levels['level1']['label'],
                'admin2_pcode': row.get(admin_levels['level2']['pcode_field']),
                'admin2_name': row.get(admin_levels['level2']['name_field']),
                'admin2_label': admin_levels['level2']['label'],
                'country': country_config['name'],
                'country_code': country_config['code']
            }
            return jsonify(response_data)
        else:
            return jsonify({
                'success': False,
                'error': 'Could not match to administrative boundaries',
                'latitude': lat,
                'longitude': lon
            })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/health')
def health():
    countries_loaded = list(boundaries_cache.keys())
    return jsonify({
        'status': 'ok', 
        'countries_loaded': countries_loaded,
        'available_countries': [c['code'] for c in get_all_countries()]
    })

@app.route('/countries')
def countries():
    """Get list of available countries with their configurations."""
    try:
        countries_list = get_all_countries()
        countries_data = []
        
        for country in countries_list:
            config = get_country_config(country['key'])
            countries_data.append({
                'code': config['code'],
                'name': config['name'],
                'key': country['key'],
                'map_center': config['map_center'],
                'admin_levels': config['admin_levels']
            })
        
        return jsonify(countries_data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    # Pre-load default country boundaries
    load_boundaries(DEFAULT_COUNTRY)
    port = int(os.getenv('PORT', 5001))
    app.run(debug=True, host='0.0.0.0', port=port)
