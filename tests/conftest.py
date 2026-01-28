import pytest
import os
import sys
import pandas as pd
import geopandas as gpd
from shapely.geometry import Polygon, Point
from unittest.mock import MagicMock, patch

# Add project root to path so we can import modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from web_app import app

@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

@pytest.fixture
def mock_country_config():
    return {
        'code': 'JM',
        'name': 'Jamaica',
        'bounds': {
            'lat_min': 17.0, 'lat_max': 19.0,
            'lon_min': -79.0, 'lon_max': -76.0
        },
        'map_center': {'lat': 18.1, 'lon': -77.3, 'zoom': 9},
        'google_maps_region': 'jm',
        'google_maps_components': 'country:JM',
        'boundary_file': 'boundaries/jamaica.geojson',
        'admin_levels': {
            'level1': {'pcode_field': 'ADM1_PCODE', 'name_field': 'ADM1_EN', 'label': 'Parish'},
            'level2': {'pcode_field': 'ADM2_PCODE', 'name_field': 'ADM2_EN', 'label': 'Community'}
        },
        'spelling_corrections': {'kingston': 'Kingston'},
        'fallback_parishes': ['Portland']
    }

@pytest.fixture
def sample_boundaries():
    # Create a simple square polygon for testing
    poly = Polygon([(-77.0, 18.0), (-76.0, 18.0), (-76.0, 19.0), (-77.0, 19.0), (-77.0, 18.0)])
    
    data = {
        'ADM1_EN': ['Test Parish'],
        'ADM1_PCODE': ['JM01'],
        'ADM2_EN': ['Test Community'],
        'ADM2_PCODE': ['JM0101'],
        'geometry': [poly]
    }
    return gpd.GeoDataFrame(data, crs="EPSG:4326")

@pytest.fixture
def sample_dataframe():
    return pd.DataFrame({
        'address': ['Test Address', '18.123, -76.567'],
        'name': ['Test Place', '']
    })

@pytest.fixture
def mock_google_api_response():
    return {
        'status': 'OK',
        'results': [{
            'geometry': {
                'location': {'lat': 18.123, 'lng': -76.567},
                'location_type': 'ROOFTOP'
            },
            'address_components': [
                {'short_name': 'JM', 'types': ['country']}
            ],
            'formatted_address': 'Test Address, Jamaica'
        }]
    }
