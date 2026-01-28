import pytest
import json
import io
from unittest.mock import patch, MagicMock

def test_geocode_single_missing_data(client):
    # Test with empty body - 400
    response = client.post('/geocode_single', json={})
    assert response.status_code == 400
    
    # Test with empty address - 400
    response = client.post('/geocode_single', json={'address': ''})
    assert response.status_code == 400

@patch('web_app.geocode_address')
@patch('web_app.load_boundaries')
def test_geocode_single_geocoding_failure(mock_load, mock_geocode, client, sample_boundaries):
    mock_load.return_value = sample_boundaries
    mock_geocode.return_value = None  # Simulate geocoding failure
    
    response = client.post('/geocode_single', json={'address': 'Nowhere'})
    
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['success'] is False
    assert data['error'] == 'Could not geocode the address'

def test_bulk_geocode_not_logged_in(client):
    # Should redirect or 401/403 (login_required decorator usually redirects to login)
    
    data = {'file': (io.BytesIO(b'address\nTest'), 'test.csv')}
    response = client.post('/geocode', data=data, content_type='multipart/form-data')
    
    # Flask-Login usually redirects to login page (302) or returns 401 depending on config
    # In web_app it's a custom decorator using wraps
    # Let's check the implementation of login_required in web_app.py if needed, 
    # but based on standard behavior it's likely a redirect.
    assert response.status_code == 302
    assert '/login' in response.headers['Location']

def test_bulk_geocode_no_file(client):
    with client.session_transaction() as sess:
        sess['logged_in'] = True
        
    response = client.post('/geocode', data={}, content_type='multipart/form-data')
    assert response.status_code == 400
    assert b'No file uploaded' in response.data

@patch('web_app.load_boundaries')
def test_boundaries_geojson_route(mock_load, client, sample_boundaries):
    mock_load.return_value = sample_boundaries
    
    # Populate the cache manually since the mock won't do it
    from web_app import boundaries_geojson_cache, boundaries_etag_cache
    import hashlib
    
    geojson_str = sample_boundaries.to_json()
    boundaries_geojson_cache['JM'] = geojson_str
    boundaries_etag_cache['JM'] = hashlib.md5(geojson_str.encode()).hexdigest()
    
    # Simple GET
    response = client.get('/boundaries.geojson?country=jamaica')
    assert response.status_code == 200
    assert response.content_type == 'application/json'
    
    data = json.loads(response.data)
    assert data['type'] == 'FeatureCollection'
    
    # Test ETag caching
    etag = response.headers.get('ETag')
    assert etag is not None
    
    # Request again with ETag
    response_cached = client.get('/boundaries.geojson?country=jamaica', headers={'If-None-Match': etag})
    assert response_cached.status_code == 304
