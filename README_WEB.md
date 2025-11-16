# Jamaica Address Geocoder - Web App

A web interface for geocoding Jamaica addresses and matching them to administrative boundaries.

## Local Development

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Create `.env` file with your Google Maps API key:
```
GOOGLE_MAPS_API_KEY=your-api-key-here
```

3. Run the app:
```bash
python web_app.py
```

4. Open browser to: http://localhost:5000

## Deploy to Render (Free Tier)

1. Create account at https://render.com

2. Create new Web Service:
   - Connect your GitHub repo or upload files
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `gunicorn web_app:app`
   - Add environment variable: `GOOGLE_MAPS_API_KEY`

3. Deploy!

## Deploy to Railway (Free Tier)

1. Create account at https://railway.app

2. Create new project:
   - Deploy from GitHub or upload files
   - Railway auto-detects Python and uses Procfile
   - Add environment variable: `GOOGLE_MAPS_API_KEY`

3. Deploy!

## Deploy to Fly.io

1. Install flyctl: https://fly.io/docs/hands-on/install-flyctl/

2. Login and launch:
```bash
fly auth login
fly launch
```

3. Set environment variable:
```bash
fly secrets set GOOGLE_MAPS_API_KEY=your-api-key-here
```

4. Deploy:
```bash
fly deploy
```

## Features

- **Drag & drop CSV upload** - Easy file upload interface
- **Semicolon-separated CSV support** - Handles your address format
- **Date conversion** - Automatically converts m/d to yyyy-mm-dd
- **Limit option** - Test with subset of addresses
- **Multiple output formats** - CSV or Excel download
- **Real-time progress** - Shows upload and processing status
- **Error handling** - Clear error messages

## CSV Format

Your CSV should be semicolon-separated with these columns:
- `date` - Format: m/d (e.g., 11/1) → converted to 2025-11-01
- `name` - Organization/place name (optional, helps geocoding)
- `address` - Street address or place name
- `hot_meals` - Or any other custom columns

Example:
```
date;name;address;hot_meals
11/1;Breds Foundation;V6JR+W5X, Treasure Beach;100
11/2;Santa Cruz Community;Santa Cruz;50
```

## How It Works

1. Upload CSV file
2. Script geocodes each address using Google Maps API
3. Matches coordinates to Jamaica administrative boundaries
4. Points outside boundaries are matched to nearest boundary
5. Downloads results with all original columns + geocoding data

## Output Columns

Original columns plus:
- `latitude` - Geocoded latitude
- `longitude` - Geocoded longitude
- `ADM3_EN` - District/community name
- `ADM2_EN` - Parish name
- `ADM1_EN` - Region name
- Other admin boundary attributes

## Cost

- **Google Maps API**: $5/1000 requests after $200 free monthly credit
- **Hosting**: Free tiers available on Render, Railway, Fly.io
- **Storage**: Boundaries file (~775 polygons) loads at startup

For 223 addresses: ~$0.06 in API costs (well within free tier)
