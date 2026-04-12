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
def test_geocode_single_geocoding_failure(mock_geocode, client):
    mock_geocode.return_value = None  # Simulate geocoding failure

    response = client.post('/geocode_single', json={'address': 'Nowhere'})

    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['success'] is False
    assert data['error'] == 'Could not geocode the address'

def test_bulk_geocode_not_logged_in(client):
    data = {'file': (io.BytesIO(b'address\nTest'), 'test.csv')}
    response = client.post('/geocode', data=data, content_type='multipart/form-data')

    # login_required decorator redirects to /login
    assert response.status_code == 302
    assert '/login' in response.headers['Location']

def test_bulk_geocode_no_file(client):
    with client.session_transaction() as sess:
        sess['logged_in'] = True

    response = client.post('/geocode', data={}, content_type='multipart/form-data')
    assert response.status_code == 400
    assert b'No file uploaded' in response.data
