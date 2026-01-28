# Humanitarian Geocoder

A multi-country web interface for geocoding addresses and matching them to administrative boundaries. Supports humanitarian response efforts across different countries with easy country switching and standardized P-code output.

## Supported Countries

- **Jamaica** - Parishes and Communities (ADM1/ADM2)
- **Mozambique** - Provinces and Districts (ADM1/ADM2)

## Features

- **Multi-country support** - Switch between countries with dropdown selector
- **Country-specific configuration** - Automatic region biasing and coordinate validation
- **Dynamic admin levels** - Labels adapt to country (Parish/Province, Community/District)
- **Interactive map** - Click anywhere to get P-code information
- **Single address lookup** - Quick geocoding with visual feedback
- **Batch CSV processing** - Upload files with multiple addresses
- **Drag & drop upload** - Easy file upload interface
- **Multiple output formats** - CSV or Excel download
- **Real-time progress** - Shows upload and processing status
- **Administrative boundary matching** - Automatic P-code assignment
- **Coordinate validation** - Country-specific bounds checking
- **Caching** - Fast boundary loading with ETag support

## Local Development

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Create `.env` file with your Google Maps API key:
```
GOOGLE_MAPS_API_KEY=your-api-key-here
SECRET_KEY=your-secret-key-here
LOGIN_USERNAME=admin
LOGIN_PASSWORD=your-password-here
```

3. Run the app:
```bash
python web_app.py
```

4. Open browser to: http://localhost:5000

## Docker Deployment

### Build and Run with Docker

```bash
# Build the image
docker build -t humanitarian-geocoder .

# Run the container
docker run -p 5000:5000 \
  -e GOOGLE_MAPS_API_KEY=your-api-key \
  -e SECRET_KEY=your-secret-key \
  -e LOGIN_USERNAME=admin \
  -e LOGIN_PASSWORD=your-password \
  humanitarian-geocoder
```

### Using Docker Compose

```bash
# Create .env file with required variables
echo "GOOGLE_MAPS_API_KEY=your-api-key" >> .env
echo "SECRET_KEY=your-secret-key" >> .env
echo "LOGIN_USERNAME=admin" >> .env
echo "LOGIN_PASSWORD=your-password" >> .env

# Start the service
docker-compose up -d

# View logs
docker-compose logs -f

# Stop the service
docker-compose down
```

## DigitalOcean App Platform Deployment

1. Push your code to a GitHub repository

2. Update `.do/app.yaml` with your repository information:
   ```yaml
   github:
     branch: main
     repo: <YOUR_GITHUB_USERNAME>/<YOUR_REPO_NAME>
   ```

3. Create a new App on DigitalOcean:
   - Go to https://cloud.digitalocean.com/apps
   - Click "Create App"
   - Select "Import from GitHub"
   - Choose your repository
   - DigitalOcean will detect the `.do/app.yaml` configuration

4. Configure environment variables (in DigitalOcean dashboard):
   - `GOOGLE_MAPS_API_KEY` (Secret)
   - `SECRET_KEY` (Secret)
   - `LOGIN_PASSWORD` (Secret)

5. Deploy!

### Manual DigitalOcean Deployment

Alternatively, deploy using `doctl` CLI:

```bash
# Install doctl
brew install doctl  # macOS
# or download from https://docs.digitalocean.com/reference/doctl/how-to/install/

# Authenticate
doctl auth init

# Deploy the app
doctl apps create --spec .do/app.yaml

# Update secrets
doctl apps update <APP_ID> --spec .do/app.yaml
```

## Alternative Deployment Options

### Deploy to Render (Free Tier)

1. Create account at https://render.com

2. Create new Web Service:
   - Connect your GitHub repo or upload files
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `gunicorn web_app:app`
   - Add environment variables: `GOOGLE_MAPS_API_KEY`, `SECRET_KEY`, `LOGIN_USERNAME`, `LOGIN_PASSWORD`

3. Deploy!

### Deploy to Railway (Free Tier)

1. Create account at https://railway.app

2. Create new project:
   - Deploy from GitHub or upload files
   - Railway auto-detects Python and uses Procfile
   - Add environment variables: `GOOGLE_MAPS_API_KEY`, `SECRET_KEY`, `LOGIN_USERNAME`, `LOGIN_PASSWORD`

3. Deploy!

### Deploy to Fly.io

### Deploy to Fly.io

1. Install flyctl: https://fly.io/docs/hands-on/install-flyctl/

2. Login and launch:
```bash
fly auth login
fly launch
```

3. Set environment variables:
```bash
fly secrets set GOOGLE_MAPS_API_KEY=your-api-key-here
fly secrets set SECRET_KEY=your-secret-key
fly secrets set LOGIN_USERNAME=admin
fly secrets set LOGIN_PASSWORD=your-password
```

4. Deploy:
```bash
fly deploy
```

## CSV Format

Your CSV can be semicolon or comma-separated with an address column. The system will automatically detect the address column.

Example (semicolon-separated):
```
date;name;address;notes
11/1;Breds Foundation;V6JR+W5X, Treasure Beach;Emergency shelter
11/2;Santa Cruz Community;Santa Cruz;Distribution point
```

Example (comma-separated):
```
organization,location,district,beneficiaries
UNICEF,Maputo Central,Maputo City,500
WFP,Beira,Sofala,1200
```

## How It Works

1. Select country from dropdown (Jamaica or Mozambique)
2. Enter single address or upload CSV file
3. System geocodes addresses using Google Maps API with country-specific region biasing
4. Validates coordinates against country boundaries
5. Matches coordinates to administrative boundaries (provinces/districts or parishes/communities)
6. Returns results with P-codes and admin level names
7. Download batch results with all original columns + geocoding data

## Output Columns

Original columns plus:
- `latitude` - Geocoded latitude
- `longitude` - Geocoded longitude
- `confidence` - Geocoding confidence level
- `ADM1_PCODE` - Admin Level 1 P-code (Province/Parish)
- `ADM1_EN` - Admin Level 1 name
- `ADM2_PCODE` - Admin Level 2 P-code (District/Community)
- `ADM2_EN` - Admin Level 2 name

## Adding New Countries

1. **Obtain boundary data**: Get GeoJSON with ADM1/ADM2 boundaries from OCHA or similar source

2. **Create country config**: Add new file `countries/<country>.py`:
```python
COUNTRY_CONFIG = {
    'code': 'XX',  # ISO 3166-1 alpha-2
    'name': 'Country Name',
    'bounds': {
        'min_lat': -10.0,
        'max_lat': 10.0,
        'min_lon': 20.0,
        'max_lon': 40.0
    },
    'map_center': {
        'lat': 0.0,
        'lon': 30.0,
        'zoom': 6
    },
    'google_maps_region': 'xx',
    'google_maps_components': 'country:XX',
    'boundary_file': 'boundaries/country.geojson',
    'admin_levels': {
        'level1': {
            'pcode_field': 'ADM1_PCODE',
            'name_field': 'ADM1_EN',
            'label': 'Province'
        },
        'level2': {
            'pcode_field': 'ADM2_PCODE',
            'name_field': 'ADM2_EN',
            'label': 'District'
        }
    }
}
```

3. **Add to registry**: Update `countries/country_config.py` AVAILABLE_COUNTRIES list

4. **Add boundary file**: Place GeoJSON in `boundaries/country.geojson`

5. **Update UI**: Country automatically appears in dropdown selector

## API Endpoints

- `GET /` - Main web interface
- `POST /geocode_single` - Geocode single address (requires `address` and `country`)
- `POST /geocode` - Batch geocode CSV (requires `file` and `country`)
- `GET /boundaries.geojson?country=<code>` - Get country boundaries
- `POST /reverse_geocode` - Get P-codes from coordinates (requires `latitude`, `longitude`, `country`)
- `GET /countries` - List available countries with configurations
- `GET /health` - Health check endpoint

## Cost

- **Google Maps API**: $5/1000 requests after $200 free monthly credit
- **Hosting**: Free tiers available on Render, Railway, Fly.io
- **Storage**: Boundaries file (~775 polygons) loads at startup

For 223 addresses: ~$0.06 in API costs (well within free tier)
