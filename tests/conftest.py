import pytest
import os
import sys
import pandas as pd
from unittest.mock import MagicMock, patch

# Add project root to path so we can import modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# This conftest serves the geocode-core unit tests (test_geocode*, test_bulk_geocode).
# The HTTP-layer tests now live in tests_django/ using DRF's APIClient.

@pytest.fixture
def mock_resolve_pcodes():
    """Sample return value for geocode.resolve_pcodes."""
    return {
        'country': 'Jamaica',
        'country_code': 'JM',
        'adm0_pcode': 'JM',
        'adm0_name': 'Jamaica',
        'adm1_pcode': 'JM01',
        'adm1_name': 'Test Parish',
        'adm2_pcode': 'JM0101',
        'adm2_name': 'Test Community',
    }

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
