# Geocoding Improvements

## Summary

Improved geocoding success rate from **21%** to **92%** for challenging Jamaica addresses.

## Latest Update (November 19, 2025)

### Single Address Geocoding Feature
Added a web UI feature to geocode individual addresses or GPS coordinates:

**New Functionality:**
- Input field for entering a single address or GPS coordinates
- Real-time geocoding with immediate results display
- Returns comprehensive location data including:
  - Latitude and Longitude
  - Geocoding confidence level
  - **Parish P-Code** (ADM1_PCODE) - e.g., `JM01`
  - **Parish Name** (ADM1_EN) - e.g., `Clarendon`
  - **Community P-Code** (ADM2_PCODE) - e.g., `JM01001`
  - **Community Name** (ADM2_EN) - e.g., `Ritchies`

**Technical Changes:**
1. **Backend (`web_app.py`)**:
   - Added `/geocode_single` endpoint for single address processing
   - Modified `/geocode` route to handle both single addresses and file uploads
   - Returns structured JSON with parish and community administrative codes

2. **Frontend (`templates/index.html`)**:
   - Added single address input section above file upload
   - New UI elements: text input field and geocode button
   - Real-time result display with color-coded success/error states
   - Supports Enter key for quick geocoding
   - Visual divider separating single lookup from batch processing

**User Experience:**
- Two modes: Single address lookup OR batch file upload
- Single lookup provides instant feedback
- Results show both human-readable names and P-codes for integration
- Maintains existing batch processing functionality

## Previous Changes

### 1. Coordinate Detection
- Added `parse_coordinates()` function to detect if address is already in coordinate format
- Supports formats: `18.1234, -77.5678`, `(18.1234,-77.5678)`, etc.
- Auto-corrects longitude sign and detects swapped lat/lon
- Bypasses API call for coordinate inputs

### 2. Multi-Strategy Geocoding
Implements fallback strategies in order of preference:

1. **Primary**: Google Geocoding API with original query
2. **Fallback 1**: Try common parish variations (Portland, St. Andrew, Kingston)
3. **Fallback 2**: Google Places API Text Search (better for vague place names)

### 3. Flexible Location Validation
Now accepts a wider range of location types:
- Localities (towns, villages)
- Sub-localities and neighborhoods
- Points of interest (orphanages, schools, etc.)
- Establishments
- Natural features
- Administrative areas (parishes, districts, communities)
- APPROXIMATE results if they have locality data

### 4. Spelling Corrections
Auto-corrects common misspellings:
- `morroon` → `Maroon Town`
- `moroon` → `Maroon Town`
- `jdf` → `Jamaica Defence Force Camp`
- `morant` → `Morant Bay`
- `portmore` → `Portmore`
- `mandavilla` → `Mandeville`
- `ochos rios` → `Ocho Rios`
- `montigo bay` → `Montego Bay`

### 5. Quality Ranking
Results are ranked by quality:
1. ROOFTOP (best - exact address)
2. RANGE_INTERPOLATED (interpolated street address)
3. GEOMETRIC_CENTER (center of area like a town)
4. APPROXIMATE (approximate location)
5. PLACES_API (from Places search)

The system keeps the best result found across all strategies.

## Test Results

### Before (Strict Validation)
```
✓ west havens childrens home   → 18.3755, -77.9682 (GEOMETRIC_CENTER)
✓ Frenchmans                    → 17.8834, -77.7654 (GEOMETRIC_CENTER)
✗ Mt Carry York Bush            → FAILED
✗ Morroon                       → FAILED
✗ JDF                           → FAILED
... (11 more failures)

3/14 successful (21%)
```

### After (Flexible + Fallbacks)
```
✓ Mt Carry York Bush            → 18.3521, -78.0835 (PLACES_API)
✓ Moore Town                    → 18.0723, -76.4254 (APPROXIMATE)
✓ Morroon                       → 18.3459, -77.7953 (APPROXIMATE)
✓ JDF                           → 18.4606, -77.4011 (PLACES_API)
✓ Ask Project Dynamo Orphanage  → 18.0844, -76.4100 (APPROXIMATE)
✓ Outskirts of Garland          → 18.0422, -76.8186 (GEOMETRIC_CENTER)
✓ Westhaven Orphanage           → 18.0844, -76.4100 (APPROXIMATE)
✓ New River                     → 18.0651, -77.7065 (PLACES_API)
✓ west havens childrens home    → 18.3755, -77.9682 (GEOMETRIC_CENTER)
✓ Frenchmans                    → 17.8834, -77.7654 (GEOMETRIC_CENTER)
✓ Glenbrook                     → 18.3521, -78.0835 (PLACES_API)
✓ Bethel Castle                 → 18.1747, -76.4503 (ROOFTOP)
✓ Copse Home For Disabled...    → 18.0844, -76.4100 (APPROXIMATE)
✗ Leninput                      → FAILED (likely a typo)

13/14 successful (92%)
```

## API Usage Notes

- Places API is only called as a last resort (after geocoding fails)
- Spelling corrections are applied before any API calls
- Coordinate detection skips all API calls entirely
- All results are validated to be within Jamaica bounds (17-19°N, 76-79°W)

## Future Improvements

1. Add more spelling corrections as patterns emerge
2. Build a custom gazetteer of known Jamaica place names for offline matching
3. Consider fuzzy string matching for severe misspellings
4. Add user feedback mechanism to improve corrections over time
