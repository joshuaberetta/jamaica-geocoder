import pytest
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point
from unittest.mock import patch, MagicMock
import json
import logging

from geocode import parse_coordinates, geocode_dataframe, spatial_join_boundaries

def test_parse_coordinates(mock_country_config):
    # Valid coordinates
    assert parse_coordinates("18.123, -77.456", mock_country_config) == (18.123, -77.456)
    assert parse_coordinates("18.123 -77.456", mock_country_config) == (18.123, -77.456)
    
    # Invalid coordinates
    assert parse_coordinates("Not a coordinate", mock_country_config) is None
    
    # Out of bounds (using Jamaica bounds from mock config)
    assert parse_coordinates("50.0, 50.0", mock_country_config) is None

@patch('geocode.urlopen')
def test_geocode_dataframe_success(mock_urlopen, sample_dataframe, mock_google_api_response, mock_country_config):
    # Setup mock response
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps(mock_google_api_response).encode('utf-8')
    mock_response.__enter__.return_value = mock_response
    mock_urlopen.return_value = mock_response

    # Prepare input DF (one address, one coordinate)
    df = sample_dataframe.copy()
    
    # Run geocoding
    # We patch os.getenv to ensure API key is present
    with patch('os.getenv', return_value='TEST_KEY'):
        result_gdf, stats = geocode_dataframe(df, delay=0.0, country_config=mock_country_config)

    assert isinstance(result_gdf, gpd.GeoDataFrame)
    assert len(result_gdf) == 2
    assert stats['successful'] == 2
    assert stats['failed'] == 0
    
    # Check "Test Address" was geocoded
    assert result_gdf.iloc[0]['latitude'] == 18.123
    assert result_gdf.iloc[0]['longitude'] == -76.567
    
    # Check coordinate string was parsed directly
    assert result_gdf.iloc[1]['latitude'] == 18.123
    assert result_gdf.iloc[1]['longitude'] == -76.567
    assert result_gdf.iloc[1]['geocode_confidence'] == 'COORDINATES'

def test_spatial_join_boundaries(sample_boundaries):
    # Point inside boundary
    point_inside = Point(-76.5, 18.5)
    
    # Point outside boundary
    point_outside = Point(-78.0, 18.5)
    
    points_df = pd.DataFrame({
        'id': [1, 2],
        'latitude': [18.5, 18.5],
        'longitude': [-76.5, -78.0]
    })
    gdf = gpd.GeoDataFrame(points_df, geometry=[point_inside, point_outside], crs="EPSG:4326")
    
    joined = spatial_join_boundaries(gdf, sample_boundaries)
    
    # Point inside should match exactly
    row_inside = joined[joined['id'] == 1].iloc[0]
    assert row_inside['ADM1_EN'] == 'Test Parish'
    
    # Point outside should be matched to nearest (which is the same one in this 1-polygon world)
    row_outside = joined[joined['id'] == 2].iloc[0]
    assert row_outside['ADM1_EN'] == 'Test Parish'
