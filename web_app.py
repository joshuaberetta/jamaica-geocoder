#!/usr/bin/env python3
"""
Web interface for Jamaica address geocoding.
Upload CSV, get geocoded results with admin boundaries.
"""

from flask import Flask, render_template, request, send_file, jsonify, redirect, url_for, session
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

# Import geocoding functions from geocode.py
from geocode import geocode_address, geocode_dataframe, spatial_join_boundaries

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

# Load boundaries once at startup
BOUNDARIES_FILE = os.getenv('BOUNDARIES_FILE', 'odpem.geojson')
boundaries_gdf = None

def load_boundaries():
    global boundaries_gdf
    if boundaries_gdf is None and Path(BOUNDARIES_FILE).exists():
        print(f"Loading boundaries from {BOUNDARIES_FILE}...")
        boundaries_gdf = gpd.read_file(BOUNDARIES_FILE)
        print(f"Loaded {len(boundaries_gdf)} boundary features")
    return boundaries_gdf

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
    return render_template('index.html', logged_in=session.get('logged_in', False))

@app.route('/geocode', methods=['POST'])
@login_required
def geocode():
    try:
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
        
        # Load boundaries
        boundaries = load_boundaries()
        if boundaries is None:
            return jsonify({'error': 'Boundary data not available'}), 500
        
        # Geocode addresses - use minimal delay to avoid timeout
        points_gdf, stats = geocode_dataframe(df, address_column='address', delay=0.05)
        
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
        
        if not address_input:
            return jsonify({'error': 'Address or GPS coordinates required'}), 400
        
        # Load boundaries
        boundaries = load_boundaries()
        if boundaries is None:
            return jsonify({'error': 'Boundary data not available'}), 500
        
        # Geocode the address
        result = geocode_address(address_input)
        
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
        
        # Extract the result
        if len(joined) > 0:
            row = joined.iloc[0]
            response_data = {
                'success': True,
                'address': address_input,
                'latitude': lat,
                'longitude': lon,
                'confidence': confidence,
                'parish_pcode': row.get('ADM1_PCODE'),
                'parish_name': row.get('ADM1_EN'),
                'community_pcode': row.get('ADM2_PCODE'),
                'community_name': row.get('ADM2_EN')
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
    """Serve the boundaries GeoJSON file reprojected to WGS84 (public endpoint)."""
    try:
        if not Path(BOUNDARIES_FILE).exists():
            return jsonify({'error': 'Boundary file not found'}), 404
        
        # Load and reproject to WGS84 for web mapping
        gdf = gpd.read_file(BOUNDARIES_FILE)
        if gdf.crs and gdf.crs != 'EPSG:4326':
            gdf = gdf.to_crs('EPSG:4326')
        
        # Return as GeoJSON
        return jsonify(json.loads(gdf.to_json()))
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/reverse_geocode', methods=['POST'])
def reverse_geocode():
    """Get pcode information for a lat/lon coordinate (public endpoint)."""
    try:
        data = request.get_json() if request.is_json else request.form
        lat = data.get('latitude') or data.get('lat')
        lon = data.get('longitude') or data.get('lon')
        
        if lat is None or lon is None:
            return jsonify({'error': 'Latitude and longitude required'}), 400
        
        try:
            lat = float(lat)
            lon = float(lon)
        except ValueError:
            return jsonify({'error': 'Invalid latitude or longitude format'}), 400
        
        # Load boundaries
        boundaries = load_boundaries()
        if boundaries is None:
            return jsonify({'error': 'Boundary data not available'}), 500
        
        # Create a point from the coordinates
        point = Point(lon, lat)
        point_gdf = gpd.GeoDataFrame(
            {'latitude': [lat], 'longitude': [lon]},
            geometry=[point],
            crs='EPSG:4326'
        )
        
        # Perform spatial join
        joined = spatial_join_boundaries(point_gdf, boundaries)
        
        # Extract the result
        if len(joined) > 0:
            row = joined.iloc[0]
            response_data = {
                'success': True,
                'latitude': lat,
                'longitude': lon,
                'parish_pcode': row.get('ADM1_PCODE'),
                'parish_name': row.get('ADM1_EN'),
                'community_pcode': row.get('ADM2_PCODE'),
                'community_name': row.get('ADM2_EN')
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
    return jsonify({'status': 'ok', 'boundaries_loaded': boundaries_gdf is not None})

if __name__ == '__main__':
    load_boundaries()
    port = int(os.getenv('PORT', 5001))
    app.run(debug=True, host='0.0.0.0', port=port)
