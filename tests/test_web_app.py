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
    with patch('web_app.get_db_conn') as mock_db:
        mock_cur = MagicMock()
        mock_cur.__enter__.return_value = mock_cur
        mock_cur.fetchall.return_value = [
            {'iso2': 'JM', 'iso3': 'JAM', 'country_name': 'Jamaica',
             'max_adm_level': 2, 'center_lon': -77.3, 'center_lat': 18.1}
        ]
        mock_conn = MagicMock()
        mock_conn.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cur
        mock_db.return_value = mock_conn

        response = client.get('/countries')

    assert response.status_code == 200
    data = json.loads(response.data)
    assert isinstance(data, list)
    assert len(data) > 0
    assert 'code' in data[0]
    assert data[0]['code'] == 'JM'

@patch('web_app.resolve_pcodes')
@patch('web_app.geocode_address')
def test_geocode_single_endpoint(mock_geocode, mock_resolve, client, mock_resolve_pcodes):
    mock_geocode.return_value = (18.123, -76.567, "ROOFTOP")
    mock_resolve.return_value = mock_resolve_pcodes

    response = client.post('/geocode_single', json={
        'address': 'Test Address',
        'country': 'JM'
    })

    assert response.status_code == 200
    data = json.loads(response.data)

    assert data['success'] is True
    assert data['latitude'] == 18.123
    assert data['adm1_name'] == 'Test Parish'
    assert data['country_code'] == 'JM'

@patch('web_app.resolve_pcodes')
@patch('web_app.geocode_dataframe')
def test_bulk_geocode_endpoint(mock_geocode_df, mock_resolve, client, mock_resolve_pcodes):
    result_gdf = gpd.GeoDataFrame({
        'address': ['Test 1'],
        'latitude': [18.123],
        'longitude': [-76.567],
        'geocode_confidence': ['ROOFTOP'],
        'geometry': [Point(-76.567, 18.123)]
    }, crs="EPSG:4326")
    stats = {'total': 1, 'successful': 1, 'failed': 0, 'skipped': 0}
    mock_geocode_df.return_value = (result_gdf, stats)
    mock_resolve.return_value = mock_resolve_pcodes

    csv_str = pd.DataFrame({'address': ['Test 1']}).to_csv(index=False)
    data = {
        'file': (io.BytesIO(csv_str.encode('utf-8')), 'test.csv'),
        'country': 'JM'
    }

    with client.session_transaction() as sess:
        sess['logged_in'] = True

    response = client.post('/geocode', data=data, content_type='multipart/form-data')

    assert response.status_code == 200
    json_response = json.loads(response.data)
    assert json_response['success'] is True
    assert json_response['filename'] == 'geocoded_addresses.csv'
