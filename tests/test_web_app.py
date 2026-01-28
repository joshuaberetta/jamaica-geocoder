import pytest
import json
import io
from unittest.mock import patch, MagicMock
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point

def test_index_route(client):
    response = client.get('/')
    assert response.status_code == 200
    assert b"Humanitarian Geocoder" in response.data

def test_countries_route(client):
    response = client.get('/countries')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert isinstance(data, list)
    assert len(data) > 0
    assert 'code' in data[0]

@patch('web_app.load_boundaries')
@patch('web_app.geocode_address')
@patch('web_app.spatial_join_boundaries')
def test_geocode_single_endpoint(mock_spatial_join, mock_geocode, mock_load, client, mock_country_config, sample_boundaries):
    # Setup mocks
    mock_load.return_value = sample_boundaries
    mock_geocode.return_value = (18.123, -76.567, "ROOFTOP")
    
    # Mock result of spatial join
    # It takes point_gdf and boundaries, returns point_gdf with boundary info
    def side_effect_spatial(point_gdf, boundaries):
        # Determine cols to add
        cols = ['ADM1_EN', 'ADM1_PCODE', 'ADM2_EN', 'ADM2_PCODE']
        for col in cols:
            point_gdf[col] = sample_boundaries.iloc[0][col]
        return point_gdf
        
    mock_spatial_join.side_effect = side_effect_spatial
    
    # Make request
    response = client.post('/geocode_single', json={
        'address': 'Test Address',
        'country': 'jamaica'
    })
    
    assert response.status_code == 200
    data = json.loads(response.data)
    
    assert data['success'] is True
    assert data['latitude'] == 18.123
    assert data['admin1_name'] == 'Test Parish'
    assert data['country_code'] == 'JM'

@patch('web_app.load_boundaries')
@patch('web_app.geocode_dataframe')
@patch('web_app.spatial_join_boundaries')
def test_bulk_geocode_endpoint(mock_spatial_join, mock_geocode_df, mock_load, client, sample_boundaries):
    # Setup mocks
    mock_load.return_value = sample_boundaries
    
    # Mock geocode_dataframe return (gdf, stats)
    result_gdf = gpd.GeoDataFrame({
        'address': ['Test 1'],
        'latitude': [18.123],
        'longitude': [-76.567],
        'geocode_confidence': ['ROOFTOP'],
        'geometry': [Point(-76.567, 18.123)]
    }, crs="EPSG:4326")
    stats = {'total': 1, 'successful': 1, 'failed': 0, 'skipped': 0}
    mock_geocode_df.return_value = (result_gdf, stats)
    
    # Mock spatial join
    def side_effect_spatial(points, boundaries):
        points['ADM1_EN'] = 'Test Parish'
        return points
    mock_spatial_join.side_effect = side_effect_spatial

    # Prepare file upload
    csv_str = pd.DataFrame({'address': ['Test 1']}).to_csv(index=False)
    data = {
        'file': (io.BytesIO(csv_str.encode('utf-8')), 'test.csv'),
        'country': 'jamaica'
    }
    
    # Login session
    with client.session_transaction() as sess:
        sess['logged_in'] = True

    response = client.post('/geocode', data=data, content_type='multipart/form-data')
    
    assert response.status_code == 200
    json_response = json.loads(response.data)
    assert json_response['success'] is True
    assert json_response['filename'] == 'geocoded_addresses.csv'
