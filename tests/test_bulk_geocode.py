"""
Tests for bulk geocoding (geocode_dataframe) across multiple countries.

Covers:
- Coordinate-only rows (no API call)
- Address-only rows (mocked API)
- Mixed rows with both coordinates and addresses
- European decimal coordinate format (Mozambique / Ukrainian data)
- Empty / NaN rows (should be skipped)
- Correct stats accounting for each country scenario
- country_hint is forwarded to geocode_address
"""

import pytest
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point
from unittest.mock import patch, call

from scripts.geocode import geocode_dataframe


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mk_df(*addresses, extra_cols=None):
    """Build a simple DataFrame with an 'address' column."""
    data = {"address": list(addresses)}
    if extra_cols:
        data.update(extra_cols)
    return pd.DataFrame(data)


# ---------------------------------------------------------------------------
# Jamaica — mixed coordinates and text addresses
# ---------------------------------------------------------------------------

class TestJamaicaBulkGeocode:
    """Jamaica: Caribbean island, standard decimal coordinates."""

    def test_all_coordinates(self):
        """All rows are valid coordinate strings — zero API calls."""
        df = _mk_df(
            "18.0061, -76.7447",  # Kingston
            "18.4762, -77.9220",  # Montego Bay
            "17.9970, -76.8530",  # Portmore
        )
        with patch("scripts.geocode.geocode_address") as mock_api:
            gdf, stats = geocode_dataframe(df, delay=0.0, country_hint="Jamaica")

        mock_api.assert_not_called()
        assert stats["total"] == 3
        assert stats["successful"] == 3
        assert stats["from_coordinates"] == 3
        assert stats["geocoded"] == 0
        assert stats["failed"] == 0
        assert stats["skipped"] == 0

        assert isinstance(gdf, gpd.GeoDataFrame)
        assert gdf.crs.to_epsg() == 4326
        assert gdf.iloc[0]["latitude"] == pytest.approx(18.0061)
        assert gdf.iloc[1]["longitude"] == pytest.approx(-77.9220)
        assert all(gdf["geocode_confidence"] == "COORDINATES")

    def test_all_addresses(self):
        """All rows are text addresses — each triggers a mocked API call."""
        df = _mk_df(
            "Half Way Tree, Kingston",
            "Dunn's River Falls",
            "Norman Manley International Airport",
        )
        api_returns = [
            (18.0102, -76.7930, "SETTLEMENT"),
            (18.4200, -77.0100, "PLACE"),
            (17.9356, -76.7877, "PLACE"),
        ]
        with patch("scripts.geocode.geocode_address", side_effect=api_returns) as mock_api:
            gdf, stats = geocode_dataframe(df, delay=0.0, country_hint="Jamaica")

        assert mock_api.call_count == 3
        # Verify country_hint is passed through
        for c in mock_api.call_args_list:
            assert "Jamaica" in c.args or "Jamaica" in str(c.kwargs)

        assert stats["successful"] == 3
        assert stats["geocoded"] == 3
        assert stats["from_coordinates"] == 0
        assert stats["failed"] == 0

        assert gdf.iloc[0]["latitude"] == pytest.approx(18.0102)
        assert gdf.iloc[2]["geocode_confidence"] == "PLACE"

    def test_mixed_rows(self):
        """Mix of coordinates, addresses, and failures."""
        df = _mk_df(
            "18.1096, -77.2975",         # coordinate → no API
            "Spanish Town",              # address → API success
            "Gibberish@@##",             # address → API failure
            "",                          # empty → skipped
        )
        with patch("scripts.geocode.geocode_address", side_effect=[
            (17.9910, -76.9571, "SETTLEMENT"),  # Spanish Town
            None,                               # Gibberish
        ]) as mock_api:
            gdf, stats = geocode_dataframe(df, delay=0.0, country_hint="Jamaica")

        assert mock_api.call_count == 2
        assert stats["total"] == 4
        assert stats["successful"] == 2
        assert stats["from_coordinates"] == 1
        assert stats["geocoded"] == 1
        assert stats["failed"] == 1
        assert stats["skipped"] == 1

        assert gdf.iloc[0]["latitude"] == pytest.approx(18.1096)
        assert gdf.iloc[1]["latitude"] == pytest.approx(17.9910)
        assert pd.isna(gdf.iloc[2]["latitude"])
        assert pd.isna(gdf.iloc[3]["latitude"])


# ---------------------------------------------------------------------------
# Mozambique — European decimal format coordinates
# ---------------------------------------------------------------------------

class TestMozambiqueBulkGeocode:
    """Mozambique: coordinates often written with comma as decimal separator."""

    def test_european_decimal_coordinates(self):
        """Comma-decimal coordinates (e.g. -24,6553835 33,3265245) are parsed correctly."""
        df = _mk_df(
            "-25,9692 32,5732",    # Maputo
            "-19,8437 34,8388",    # Beira
            "-15,1167 39,2667",    # Nacala
        )
        with patch("scripts.geocode.geocode_address") as mock_api:
            gdf, stats = geocode_dataframe(df, delay=0.0, country_hint="Mozambique")

        mock_api.assert_not_called()
        assert stats["from_coordinates"] == 3
        assert stats["successful"] == 3

        assert gdf.iloc[0]["latitude"] == pytest.approx(-25.9692)
        assert gdf.iloc[0]["longitude"] == pytest.approx(32.5732)
        assert gdf.iloc[1]["latitude"] == pytest.approx(-19.8437)

    def test_mixed_decimal_formats(self):
        """Standard and European decimal coordinates are both parsed correctly."""
        df = _mk_df(
            "-24.6554, 33.3265",   # standard decimal
            "-24,6554 33,3265",    # European decimal
        )
        with patch("scripts.geocode.geocode_address") as mock_api:
            gdf, stats = geocode_dataframe(df, delay=0.0, country_hint="Mozambique")

        mock_api.assert_not_called()
        assert stats["from_coordinates"] == 2
        assert gdf.iloc[0]["latitude"] == pytest.approx(gdf.iloc[1]["latitude"], abs=1e-4)
        assert gdf.iloc[0]["longitude"] == pytest.approx(gdf.iloc[1]["longitude"], abs=1e-4)

    def test_addresses_with_country_hint(self):
        """Text addresses forward 'Mozambique' as the country_hint."""
        df = _mk_df("Matola", "Nampula Cidade")
        with patch("scripts.geocode.geocode_address", side_effect=[
            (-25.9623, 32.4589, "SETTLEMENT"),
            (-15.1165, 39.2666, "SETTLEMENT"),
        ]) as mock_api:
            gdf, stats = geocode_dataframe(df, delay=0.0, country_hint="Mozambique")

        assert mock_api.call_count == 2
        for c in mock_api.call_args_list:
            assert "Mozambique" in c.args or "Mozambique" in str(c.kwargs)

        assert stats["geocoded"] == 2
        assert gdf.iloc[0]["latitude"] == pytest.approx(-25.9623)


# ---------------------------------------------------------------------------
# Haiti — all failures and partial results
# ---------------------------------------------------------------------------

class TestHaitiBulkGeocode:
    """Haiti: test edge-cases like all-fail batches and NaN rows."""

    def test_all_api_failures(self):
        """When every API call returns None the stats reflect all failures."""
        df = _mk_df(
            "Quartier Morin",
            "Section Communale inconnue",
            "Lieu Dit Inexistant",
        )
        with patch("scripts.geocode.geocode_address", return_value=None):
            gdf, stats = geocode_dataframe(df, delay=0.0, country_hint="Haiti")

        assert stats["total"] == 3
        assert stats["successful"] == 0
        assert stats["failed"] == 3
        assert stats["skipped"] == 0
        assert all(pd.isna(gdf["latitude"]))

    def test_nan_and_none_rows_are_skipped(self):
        """NaN, None, and empty-string addresses are skipped, not failed."""
        df = pd.DataFrame({
            "address": [None, float("nan"), "", "Pétionville"],
        })
        with patch("scripts.geocode.geocode_address", return_value=(18.5122, -72.2894, "SETTLEMENT")):
            gdf, stats = geocode_dataframe(df, delay=0.0, country_hint="Haiti")

        assert stats["skipped"] == 3
        assert stats["successful"] == 1
        assert stats["geocoded"] == 1

    def test_partial_success(self):
        """Some rows geocode, some fail; geometry column only set for successes."""
        df = _mk_df(
            "Port-au-Prince",           # success
            "18.5433, -72.3395",        # coordinate
            "Nonexistent locality XYZ", # failure
        )
        with patch("scripts.geocode.geocode_address", side_effect=[
            (18.5433, -72.3395, "SETTLEMENT"),
            None,
        ]):
            gdf, stats = geocode_dataframe(df, delay=0.0, country_hint="Haiti")

        assert stats["successful"] == 2
        assert stats["from_coordinates"] == 1
        assert stats["geocoded"] == 1
        assert stats["failed"] == 1

        # Geometry should be a Point for successful rows, None for failures
        assert isinstance(gdf.iloc[0].geometry, Point)
        assert isinstance(gdf.iloc[1].geometry, Point)
        assert gdf.iloc[2].geometry is None


# ---------------------------------------------------------------------------
# Nigeria — large mixed batch
# ---------------------------------------------------------------------------

class TestNigeriaBulkGeocode:
    """Nigeria: large batch verifying aggregate stats are correct."""

    def test_large_mixed_batch(self):
        """10-row batch: 3 coordinates, 4 successful geocodes, 2 failures, 1 skip."""
        rows = [
            "9.0765, 7.3986",        # Abuja coordinate
            "6.4541, 3.3947",        # Lagos coordinate
            "12.0022, 8.5920",       # Kano coordinate
            "Ibadan Central",        # geocoded
            "Enugu GRA",             # geocoded
            "Kaduna North",          # geocoded
            "Abeokuta South",        # geocoded
            "Fake Place XYZ",        # failure
            "Unknown Area 999",      # failure
            "",                      # skip
        ]
        df = _mk_df(*rows)
        api_side_effects = [
            (7.3775, 3.9470, "SETTLEMENT"),   # Ibadan
            (6.4483, 7.5136, "SETTLEMENT"),   # Enugu
            (10.5105, 7.4165, "SETTLEMENT"),  # Kaduna
            (7.1475, 3.3619, "SETTLEMENT"),   # Abeokuta
            None,                             # Fake Place
            None,                             # Unknown Area
        ]
        with patch("scripts.geocode.geocode_address", side_effect=api_side_effects):
            gdf, stats = geocode_dataframe(df, delay=0.0, country_hint="Nigeria")

        assert stats["total"] == 10
        assert stats["from_coordinates"] == 3
        assert stats["geocoded"] == 4
        assert stats["successful"] == 7
        assert stats["failed"] == 2
        assert stats["skipped"] == 1

        # Coordinate rows
        assert gdf.iloc[0]["latitude"] == pytest.approx(9.0765)
        assert gdf.iloc[1]["longitude"] == pytest.approx(3.3947)
        # First geocoded row (index 3)
        assert gdf.iloc[3]["latitude"] == pytest.approx(7.3775)
        # Failure row (index 7)
        assert pd.isna(gdf.iloc[7]["latitude"])
        assert gdf.iloc[7].geometry is None


# ---------------------------------------------------------------------------
# Ukraine — European decimal coordinates with name column
# ---------------------------------------------------------------------------

class TestUkraineBulkGeocode:
    """Ukraine: European decimal coordinates and name+address column combination."""

    def test_name_column_combined_with_address(self):
        """When a 'name' column is present it is prepended to the address query."""
        df = pd.DataFrame({
            "name":    ["Lviv City Council", "Odesa Port"],
            "address": ["вул. Підвальна, 1", "вул. Приморська, 6"],
        })
        captured_queries = []

        def fake_geocode(query, country_hint=None):
            captured_queries.append(query)
            return (49.8397, 24.0297, "PLACE")

        with patch("scripts.geocode.geocode_address", side_effect=fake_geocode):
            gdf, stats = geocode_dataframe(df, delay=0.0, country_hint="Ukraine")

        assert "Lviv City Council" in captured_queries[0]
        assert "вул. Підвальна, 1" in captured_queries[0]
        assert "Odesa Port" in captured_queries[1]
        assert stats["geocoded"] == 2

    def test_european_coordinates_with_name_column(self):
        """Coordinate strings in address column are parsed; name column is irrelevant."""
        df = pd.DataFrame({
            "name":    ["Kyiv",   "Kharkiv"],
            "address": ["50,4501 30,5234", "49,9935 36,2304"],
        })
        with patch("scripts.geocode.geocode_address") as mock_api:
            gdf, stats = geocode_dataframe(df, delay=0.0, country_hint="Ukraine")

        mock_api.assert_not_called()
        assert stats["from_coordinates"] == 2
        assert gdf.iloc[0]["latitude"] == pytest.approx(50.4501)
        assert gdf.iloc[1]["longitude"] == pytest.approx(36.2304)


# ---------------------------------------------------------------------------
# Custom address column name
# ---------------------------------------------------------------------------

class TestCustomAddressColumn:
    """geocode_dataframe supports an arbitrary address_column name."""

    def test_custom_column_name(self):
        df = pd.DataFrame({"location": ["18.0061, -76.7447", "Spanish Town"]})
        with patch("scripts.geocode.geocode_address", return_value=(17.9910, -76.9571, "SETTLEMENT")):
            gdf, stats = geocode_dataframe(
                df, address_column="location", delay=0.0, country_hint="Jamaica"
            )

        assert stats["from_coordinates"] == 1
        assert stats["geocoded"] == 1
        assert stats["successful"] == 2


# ---------------------------------------------------------------------------
# GeoDataFrame output structure
# ---------------------------------------------------------------------------

class TestOutputStructure:
    """Verify the GeoDataFrame shape and dtypes are consistent."""

    def test_output_columns_present(self):
        df = _mk_df("18.0061, -76.7447")
        gdf, _ = geocode_dataframe(df, delay=0.0)

        for col in ("latitude", "longitude", "geocode_confidence", "geometry"):
            assert col in gdf.columns

    def test_crs_is_wgs84(self):
        df = _mk_df("18.0061, -76.7447")
        gdf, _ = geocode_dataframe(df, delay=0.0)
        assert gdf.crs is not None
        assert gdf.crs.to_epsg() == 4326

    def test_geometry_point_coordinates_match(self):
        df = _mk_df("18.0061, -76.7447")
        gdf, _ = geocode_dataframe(df, delay=0.0)
        pt = gdf.iloc[0].geometry
        assert isinstance(pt, Point)
        assert pt.x == pytest.approx(-76.7447)
        assert pt.y == pytest.approx(18.0061)
