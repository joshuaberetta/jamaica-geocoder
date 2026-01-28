"""Mozambique country configuration."""

COUNTRY_CONFIG = {
    'code': 'MZ',
    'name': 'Mozambique',
    'bounds': {
        'lat_min': -27.0,
        'lat_max': -10.0,
        'lon_min': 30.0,
        'lon_max': 41.0
    },
    'map_center': {
        'lat': -18.665695,
        'lon': 35.529562,
        'zoom': 6
    },
    'google_maps_region': 'mz',
    'google_maps_components': 'country:MZ',
    'boundary_file': 'boundaries/mozambique.geojson',
    'admin_levels': {
        'level1': {
            'pcode_field': 'adm1_pcode',
            'name_field': 'adm1_name',
            'label': 'Province'
        },
        'level2': {
            'pcode_field': 'adm2_pcode',
            'name_field': 'adm2_name',
            'label': 'District'
        }
    },
    'spelling_corrections': {
        # Add Mozambique-specific spelling corrections as needed
    },
    'fallback_parishes': []  # Mozambique doesn't use this pattern
}
