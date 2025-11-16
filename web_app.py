#!/usr/bin/env python3
"""
Web interface for Jamaica address geocoding.
Upload CSV, get geocoded results with admin boundaries.
"""

from flask import Flask, render_template, request, send_file, jsonify
from werkzeug.utils import secure_filename
import os
import io
import pandas as pd
import geopandas as gpd
from pathlib import Path
import tempfile
from dotenv import load_dotenv

# Import geocoding functions from geocode.py
from geocode import geocode_address, geocode_dataframe, spatial_join_boundaries

load_dotenv()

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.config['UPLOAD_FOLDER'] = tempfile.gettempdir()

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

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/geocode', methods=['POST'])
def geocode():
    try:
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
        
        # Geocode addresses
        points_gdf = geocode_dataframe(df, address_column='address', delay=0.1)
        
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
            return send_file(
                output,
                mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                as_attachment=True,
                download_name='geocoded_addresses.xlsx'
            )
        else:
            result_df.to_csv(output, index=False)
            output.seek(0)
            return send_file(
                output,
                mimetype='text/csv',
                as_attachment=True,
                download_name='geocoded_addresses.csv'
            )
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'boundaries_loaded': boundaries_gdf is not None})

if __name__ == '__main__':
    load_boundaries()
    port = int(os.getenv('PORT', 5001))
    app.run(debug=True, host='0.0.0.0', port=port)
