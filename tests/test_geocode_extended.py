import pytest
import pandas as pd
import json
from unittest.mock import patch, MagicMock
from scripts.geocode import geocode_address, geocode_dataframe

@patch('scripts.geocode.urlopen')
def test_geocode_address_api_failure(mock_urlopen):
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps({'status': 'ZERO_RESULTS', 'results': []}).encode('utf-8')
    mock_response.__enter__.return_value = mock_response
    mock_urlopen.return_value = mock_response

    with patch('os.getenv', return_value='TEST_KEY'):
        result = geocode_address("Nonexistent Place")

    assert result is None

@patch('scripts.geocode.geocode_address')
def test_geocode_dataframe_failure(mock_geocode_addr):
    mock_geocode_addr.side_effect = [
        (18.123, -76.567, "ROOFTOP"),  # Good Address
        None                            # Bad Address (API failure)
    ]

    df = pd.DataFrame({'address': ['Good Address', 'Bad Address']})

    with patch('os.getenv', return_value='TEST_KEY'):
        result_gdf, stats = geocode_dataframe(df, delay=0.0, country_hint='Jamaica')

    assert len(result_gdf) == 2
    assert stats['successful'] == 1
    assert stats['failed'] == 1

    assert result_gdf.iloc[0]['latitude'] == 18.123

    assert pd.isna(result_gdf.iloc[1]['latitude'])
