"""Country configuration factory and utilities."""

import importlib
from typing import Dict, Any, List


# Available countries
AVAILABLE_COUNTRIES = ['jamaica', 'mozambique']
DEFAULT_COUNTRY = 'jamaica'


def get_country_config(country_code: str) -> Dict[str, Any]:
    """
    Load country configuration by country code or name.
    
    Parameters:
    - country_code: Country code (JM, MZ) or country name (jamaica, mozambique)
    
    Returns:
    - Dictionary with country configuration
    
    Raises:
    - ValueError: If country is not supported
    """
    # Normalize input
    country_key = country_code.lower().strip()
    
    # Map country codes to module names
    code_to_country = {
        'jm': 'jamaica',
        'mz': 'mozambique',
        'jamaica': 'jamaica',
        'mozambique': 'mozambique'
    }
    
    country_module = code_to_country.get(country_key)
    
    if not country_module:
        raise ValueError(
            f"Unsupported country: {country_code}. "
            f"Available countries: {', '.join(AVAILABLE_COUNTRIES)}"
        )
    
    # Dynamically import the country module
    try:
        module = importlib.import_module(f'countries.{country_module}')
        return module.COUNTRY_CONFIG
    except ImportError as e:
        raise ValueError(f"Failed to load country configuration for {country_code}: {e}")


def get_all_countries() -> List[Dict[str, str]]:
    """
    Get list of all available countries with basic info.
    
    Returns:
    - List of dictionaries with code and name for each country
    """
    countries = []
    for country in AVAILABLE_COUNTRIES:
        try:
            config = get_country_config(country)
            countries.append({
                'code': config['code'],
                'name': config['name'],
                'key': country
            })
        except Exception:
            continue
    return countries


def validate_coordinates(lat: float, lon: float, country_config: Dict[str, Any]) -> bool:
    """
    Validate if coordinates fall within country bounds.
    
    Parameters:
    - lat: Latitude
    - lon: Longitude
    - country_config: Country configuration dictionary
    
    Returns:
    - True if coordinates are within bounds, False otherwise
    """
    bounds = country_config['bounds']
    
    lat_valid = bounds['lat_min'] <= lat <= bounds['lat_max']
    lon_valid = bounds['lon_min'] <= lon <= bounds['lon_max']
    
    return lat_valid and lon_valid


def normalize_longitude(lon: float, country_config: Dict[str, Any]) -> float:
    """
    Normalize longitude sign based on country location.
    For western hemisphere countries, ensure longitude is negative.
    For eastern hemisphere countries, ensure longitude is positive.
    
    Parameters:
    - lon: Longitude value
    - country_config: Country configuration dictionary
    
    Returns:
    - Normalized longitude
    """
    bounds = country_config['bounds']
    
    # If expected bounds are negative (western hemisphere)
    if bounds['lon_max'] < 0:
        return -abs(lon)
    # If expected bounds are positive (eastern hemisphere)
    else:
        return abs(lon)
