# Geocoder API — Usage Guide

This document describes how to use the geocoding API to resolve coordinates or free-text addresses into administrative boundary P-codes.

---

## Base URL

| Environment | URL |
|-------------|-----|
| Production | `https://geocoder.imtools.info` |
| Local development | `http://localhost:5001` |

Examples in this document use `http://localhost:5001`. Replace with `https://geocoder.imtools.info` when targeting the production deployment.

---

## `GET /geocode`

Resolves a single point or address into country, admin-level names, and P-codes. **No authentication required.**

### Query Parameters

| Parameter | Aliases | Type | Required | Description |
|-----------|---------|------|----------|-------------|
| `lat` | `latitude` | float | Yes (if no `address`) | Decimal latitude, WGS84 |
| `lon` | `longitude` | float | Yes (if no `address`) | Decimal longitude, WGS84 |
| `address` | — | string | Yes (if no `lat`/`lon`) | Free-text address, place name, or coordinate string |
| `country` | — | string | No | ISO 3166-1 alpha-2 code (e.g., `JM`) — scopes the lookup to one country |

You must supply **either** `lat` + `lon` **or** `address`. Supplying both will use `lat`/`lon` and ignore `address`.

---

### Response — Success (`200`)

```json
{
  "success": true,
  "latitude": 17.9712,
  "longitude": -76.7936,
  "confidence": "SETTLEMENT",
  "country": "Jamaica",
  "country_code": "JM",
  "adm0_pcode": "JM",
  "adm0_name": "Jamaica",
  "adm1_pcode": "JM001",
  "adm1_name": "Kingston",
  "adm2_pcode": "JM001001",
  "adm2_name": "Kingston Central"
}
```

**Fields returned:**

| Field | Type | Description |
|-------|------|-------------|
| `success` | bool | Always `true` on a successful response |
| `latitude` | float | Resolved or echoed latitude |
| `longitude` | float | Resolved or echoed longitude |
| `confidence` | string | Present when an address was geocoded (see below) |
| `country` | string | Country name |
| `country_code` | string | ISO2 country code |
| `adm0_pcode` / `adm0_name` | string | Country-level P-code and name (ADM0) |
| `adm1_pcode` / `adm1_name` | string | Admin level 1 P-code and name (e.g., Province/State) |
| `adm2_pcode` / `adm2_name` | string | Admin level 2 P-code and name, if available |
| `adm3_pcode` / `adm3_name` | string | Admin level 3 P-code and name, if available |
| `adm4_pcode` / `adm4_name` | string | Admin level 4 P-code and name, if available |

Higher admin levels (`adm3_*`, `adm4_*`) are only present if the country's data includes them. Always check for existence before accessing.

#### `confidence` Values

Returned only when an `address` string was geocoded (not present for raw coordinate lookups, or when it equals `COORDINATES`).

| Value | Meaning |
|-------|---------|
| `COORDINATES` | The `address` string was parsed directly as coordinates — no API call was made |
| `SETTLEMENT` | Matched to a locality, town, neighborhood, or similar place |
| `AREA` | Matched to an administrative region or postal code |
| `PLACE` | Matched to a specific establishment or premise |
| `APPROXIMATE` | Low-confidence match |
| `ROOFTOP` | Google Geocoding API: exact street-level match |
| `RANGE_INTERPOLATED` | Google Geocoding API: interpolated street address |
| `GEOMETRIC_CENTER` | Google Geocoding API: center of a polygon or route |

---

### Response — Errors

| Status | Body | Cause |
|--------|------|-------|
| `400` | `{"error": "Provide lat/lon or address parameters"}` | Neither `lat`/`lon` nor `address` was supplied |
| `400` | `{"error": "Invalid latitude or longitude"}` | `lat` or `lon` could not be parsed as a float |
| `404` | `{"success": false, "error": "Could not geocode address"}` | Address geocoding returned no result |
| `404` | `{"success": false, "error": "Point outside known boundaries"}` | Coordinates fall outside all loaded admin boundaries |
| `500` | `{"error": "..."}` | Unexpected server error |

---

### Examples

#### Coordinate lookup

```http
GET /geocode?lat=17.9712&lon=-76.7936
```

```bash
curl "http://localhost:5001/geocode?lat=17.9712&lon=-76.7936"
```

#### Coordinate lookup scoped to a country

```http
GET /geocode?lat=17.9712&lon=-76.7936&country=JM
```

#### Coordinate string passed as address (no Google API call)

Coordinate strings are detected automatically — no API call is made.

```http
GET /geocode?address=17.9712%2C-76.7936
```

Both `17.9712, -76.7936` and `17.9712 -76.7936` (space-separated) are supported. European decimal-comma notation (`17,9712`) is also accepted.

#### Free-text address

```http
GET /geocode?address=Kingston%20Central%2C%20Jamaica
```

```bash
curl "http://localhost:5001/geocode?address=Kingston+Central,+Jamaica"
```

#### Free-text address with country scope

Supplying `country` biases geocoding toward that country and restricts the P-code lookup to it.

```http
GET /geocode?address=New+Kingston&country=JM
```

---

## Integration Tips

### Checking whether coordinates are in a known area

If the point is outside any loaded administrative boundary, the API returns `404` with `"success": false`. Treat this as a "no match" rather than a hard error.

```python
import requests

resp = requests.get(
    "http://localhost:5001/geocode",
    params={"lat": 17.9712, "lon": -76.7936, "country": "JM"},
)

if resp.status_code == 200:
    data = resp.json()
    print(data.get("adm1_name"))  # e.g. "Kingston"
elif resp.status_code == 404:
    print("Point not found:", resp.json().get("error"))
else:
    resp.raise_for_status()
```

### JavaScript / TypeScript fetch

```typescript
async function geocodePoint(lat: number, lon: number, country?: string) {
  const params = new URLSearchParams({
    lat: String(lat),
    lon: String(lon),
    ...(country ? { country } : {}),
  });

  const res = await fetch(`http://localhost:5001/geocode?${params}`);
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`Geocoder error ${res.status}`);
  return res.json();
}
```

### Handling admin levels dynamically

Countries vary in how many admin levels are loaded. Iterate defensively:

```python
result = resp.json()
for level in range(5):
    pcode = result.get(f"adm{level}_pcode")
    name  = result.get(f"adm{level}_name")
    if pcode:
        print(f"ADM{level}: {name} ({pcode})")
```

---

## `POST /geocode` — Batch Upload

Accepts a CSV or Excel file with an `address` column and returns a geocoded file with P-code columns appended. **Authentication required** (session cookie from `POST /login`).

### Authentication

```bash
# Log in and save the session cookie
curl -c cookies.txt -X POST http://localhost:5001/login \
  -d "username=kobo&password=kobokobo"
```

### Request

`Content-Type: multipart/form-data`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `file` | file | Yes | CSV (`;`-delimited) or XLSX. Must contain an `address` column. |
| `country` | string | No | ISO2 code — scopes P-code lookup and biases address geocoding |
| `format` | string | No | Output format: `csv` (default) or `xlsx` |
| `output_filename` | string | No | Suggested filename for the download |
| `limit` | integer | No | Process only the first N rows |

### Input File Format

The file must have at minimum an `address` column. An optional `name` column, if present, is prepended to the address query to improve geocoding accuracy.

```
name,address
Coronation Market,"King Street, Kingston"
Norman Manley Airport,"Kingston, Jamaica"
```

Addresses can also be coordinate strings:

```
address
17.9712, -76.7936
(18.0061, -76.7498)
```

### Response

Returns the original file with these columns appended for each row:

- `lat`, `lon`
- `confidence`
- `country`, `country_code`
- `adm0_pcode`, `adm0_name`
- `adm1_pcode`, `adm1_name`
- `adm2_pcode`, `adm2_name` *(if available)*
- `adm3_pcode`, `adm3_name` *(if available)*

Rows that could not be geocoded will have empty values in these columns.

### Example

```bash
curl -b cookies.txt -X POST http://localhost:5001/geocode \
  -F "file=@locations.csv" \
  -F "country=JM" \
  -F "format=xlsx" \
  -o geocoded_locations.xlsx
```
