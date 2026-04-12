import pytest
import pandas as pd
import geopandas as gpd
from unittest.mock import patch, MagicMock
import json

from geocode import parse_coordinates, geocode_dataframe

def test_parse_coordinates_basic():
    # Valid coordinates with period as decimal separator
    assert parse_coordinates("18.123, -77.456") == (18.123, -77.456)
    assert parse_coordinates("18.123 -77.456") == (18.123, -77.456)

    # Valid coordinates with comma as decimal separator (European format)
    assert parse_coordinates("18,123 -77,456") == (18.123, -77.456)
    assert parse_coordinates("18,123, -77,456") == (18.123, -77.456)

    # Invalid input
    assert parse_coordinates("Not a coordinate") is None

def test_parse_coordinates_global_range():
    # Valid anywhere on earth — no country bounds enforcement
    assert parse_coordinates("50.0, 50.0") == (50.0, 50.0)
    assert parse_coordinates("-24.6553835 33.3265245") == (-24.6553835, 33.3265245)

    # Out-of-range values
    assert parse_coordinates("91.0, 0.0") is None   # lat > 90
    assert parse_coordinates("0.0, 181.0") is None   # lon > 180

def test_parse_coordinates_european_decimal():
    """European comma-decimal format used in Mozambique data."""
    result = parse_coordinates("-24,6553835 33,3265245")
    assert result is not None
    lat, lon = result
    assert abs(lat - (-24.6553835)) < 0.0001
    assert abs(lon - 33.3265245) < 0.0001

@patch('geocode.urlopen')
def test_geocode_dataframe_success(mock_urlopen, sample_dataframe, mock_google_api_response):
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps(mock_google_api_response).encode('utf-8')
    mock_response.__enter__.return_value = mock_response
    mock_urlopen.return_value = mock_response

    df = sample_dataframe.copy()

    with patch('os.getenv', return_value='TEST_KEY'):
        result_gdf, stats = geocode_dataframe(df, delay=0.0, country_hint='Jamaica')

    assert isinstance(result_gdf, gpd.GeoDataFrame)
    assert len(result_gdf) == 2
    assert stats['successful'] == 2
    assert stats['failed'] == 0
    assert stats['from_coordinates'] == 1   # "18.123, -76.567"
    assert stats['geocoded'] == 1           # "Test Address"

    assert result_gdf.iloc[0]['latitude'] == 18.123
    assert result_gdf.iloc[0]['longitude'] == -76.567
    assert result_gdf.iloc[1]['geocode_confidence'] == 'COORDINATES'

@patch('geocode.get_db_conn')
def test_resolve_pcodes_mock(mock_db_conn, mock_resolve_pcodes):
    """resolve_pcodes returns a pcode dict from DB."""
    from geocode import resolve_pcodes

    mock_cur = MagicMock()
    mock_cur.fetchone.return_value = {
        'iso2': 'JM', 'iso3': 'JAM', 'country_name': 'Jamaica', 'adm_level': 2,
        'adm0_pcode': 'JM', 'adm0_name': 'Jamaica',
        'adm1_pcode': 'JM01', 'adm1_name': 'Test Parish',
        'adm2_pcode': 'JM0101', 'adm2_name': 'Test Community',
        'adm3_pcode': None, 'adm3_name': None,
        'adm4_pcode': None, 'adm4_name': None,
    }
    mock_cur.__enter__ = lambda s: s
    mock_cur.__exit__ = MagicMock(return_value=False)

    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cur
    mock_conn.__enter__ = lambda s: s
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_db_conn.return_value = mock_conn

    result = resolve_pcodes(18.123, -76.567, iso2='JM')

    assert result is not None
    assert result['country_code'] == 'JM'
    assert result['adm1_pcode'] == 'JM01'
    assert result['adm1_name'] == 'Test Parish'
    assert 'adm3_pcode' not in result   # None values are excluded
