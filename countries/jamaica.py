"""Jamaica country configuration."""

COUNTRY_CONFIG = {
    'code': 'JM',
    'name': 'Jamaica',
    'bounds': {
        'lat_min': 17.0,
        'lat_max': 19.0,
        'lon_min': -79.0,
        'lon_max': -76.0
    },
    'map_center': {
        'lat': 18.1096,
        'lon': -77.2975,
        'zoom': 9
    },
    'google_maps_region': 'jm',
    'google_maps_components': 'country:JM',
    'boundary_file': 'boundaries/jamaica.geojson',
    'admin_levels': {
        'level1': {
            'pcode_field': 'ADM1_PCODE',
            'name_field': 'ADM1_EN',
            'label': 'Parish'
        },
        'level2': {
            'pcode_field': 'ADM2_PCODE',
            'name_field': 'ADM2_EN',
            'label': 'Community'
        }
    },
    'spelling_corrections': {
        'morroon': 'Maroon Town',
        'moroon': 'Maroon Town',
        'morant': 'Morant Bay',
        'portmore': 'Portmore',
        'mandavilla': 'Mandeville',
        'ochos rios': 'Ocho Rios',
        'montigo bay': 'Montego Bay',
        'jdf': 'Jamaica Defence Force Camp',
    },
    'fallback_parishes': ['Portland', 'St. Andrew', 'Kingston']
}
