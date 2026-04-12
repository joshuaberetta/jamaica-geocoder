# Frontend Migration Plan: TypeScript + Mantine

Migrate the current Jinja2/vanilla-JS frontend to a React + TypeScript SPA using
[Mantine v7](https://mantine.dev/) as the component library. The Flask backend
remains unchanged — it will serve the compiled React build in production.

---

## Current State

| Concern | Current |
|---|---|
| Templating | Jinja2 (`templates/index.html`, `templates/login.html`) |
| Styling | ~700 lines of inline CSS per template |
| Interactivity | Vanilla JS in `<script>` blocks |
| Map | Leaflet.js loaded via CDN |
| Auth | Flask session cookies (redirect on 401) |
| Build | None — served directly by Flask |

### Existing UI Surfaces

1. **Header** — Kobo logo, app title/tagline, Sign In / Sign Out button
2. **Country selector** — populated from `GET /countries`
3. **Single address lookup** — text input + Geocode button + result panel
4. **Map section** — Leaflet map, click-to-geocode, GeoJSON boundary overlay, level selector
5. **Batch upload** — file drag-drop, format/filename/limit options, progress bar, stats grid,
   auto-download + "Download Again"
6. **Login page** — username + password form (separate route `/login`)

---

## Target Stack

| Concern | New |
|---|---|
| Framework | React 18 + TypeScript |
| Build tool | Vite |
| Component library | Mantine v7 (`@mantine/core`, `@mantine/hooks`, `@mantine/form`, `@mantine/dropzone`, `@mantine/notifications`) |
| Map | `react-leaflet` v4 + `leaflet` |
| Routing | React Router v6 (two routes: `/` and `/login`) |
| HTTP | Native `fetch` with typed wrappers (no additional client lib needed) |
| Auth | Existing Flask session cookies — no changes to backend auth |

---

## Phase 1 — Project Scaffold

```
frontend/
├── index.html            # Vite entry point
├── vite.config.ts
├── tsconfig.json
├── package.json
└── src/
    ├── main.tsx
    ├── App.tsx
    ├── api/
    │   ├── types.ts
    │   └── client.ts
    ├── components/
    │   ├── AppHeader.tsx
    │   ├── CountrySelect.tsx
    │   ├── SingleAddressLookup.tsx
    │   ├── MapSection.tsx
    │   ├── BatchUpload.tsx
    │   ├── PcodeResultCard.tsx
    │   └── StatsGrid.tsx
    ├── pages/
    │   ├── MainPage.tsx
    │   └── LoginPage.tsx
    └── hooks/
        ├── useCountries.ts
        ├── useAvailableLevels.ts
        └── useAuth.ts
```

### Setup commands

```bash
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install @mantine/core @mantine/hooks @mantine/form @mantine/dropzone \
            @mantine/notifications @emotion/react
npm install react-router-dom
npm install leaflet react-leaflet
npm install -D @types/leaflet
```

### `vite.config.ts` — dev proxy

In development, proxy API calls to the Flask server so `fetch('/countries')`
just works without CORS issues:

```ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/countries': 'http://localhost:5001',
      '/api': 'http://localhost:5001',
      '/boundaries.geojson': 'http://localhost:5001',
      '/geocode': 'http://localhost:5001',
      '/geocode_single': 'http://localhost:5001',
      '/reverse_geocode': 'http://localhost:5001',
      '/login': 'http://localhost:5001',
      '/logout': 'http://localhost:5001',
      '/health': 'http://localhost:5001',
    },
  },
  build: {
    outDir: '../static',   // Flask picks this up
    emptyOutDir: true,
  },
})
```

---

## Phase 2 — API Types & Client (`src/api/`)

### `types.ts`

```ts
export interface Country {
  code: string;       // ISO2
  iso3: string;
  name: string;
  key: string;
  max_adm_level: number;
  map_center: { lat: number; lon: number; zoom: number };
}

export interface PcodeResult {
  success: boolean;
  latitude?: number;
  longitude?: number;
  confidence?: string;
  country?: string;
  adm0_pcode?: string; adm0_name?: string;
  adm1_pcode?: string; adm1_name?: string;
  adm2_pcode?: string; adm2_name?: string;
  adm3_pcode?: string; adm3_name?: string;
  adm4_pcode?: string; adm4_name?: string;
  address?: string;
  error?: string;
}

export interface AvailableLevels {
  iso2: string;
  levels: number[];
}

export interface BatchStats {
  total: number;
  successful: number;
  failed: number;
  skipped: number;
}

export interface BatchResult {
  success: boolean;
  stats: BatchStats;
  file_data: string;   // base64
  filename: string;
  mimetype: string;
  error?: string;
}
```

### `client.ts`

Typed `fetch` wrappers — all return the typed response or throw on HTTP error:

```ts
export async function fetchCountries(): Promise<Country[]>
export async function fetchAvailableLevels(iso2: string): Promise<AvailableLevels>
export async function geocodeSingle(address: string, country?: string): Promise<PcodeResult>
export async function reverseGeocode(lat: number, lon: number, country?: string): Promise<PcodeResult>
export async function geocodeBatch(form: FormData): Promise<BatchResult>
export async function checkAuth(): Promise<{ logged_in: boolean }>
```

---

## Phase 3 — Component Mapping

### `AppHeader`

| Current | Mantine |
|---|---|
| `.header` div with flexbox | `AppShell.Header` |
| Kobo SVG logo + tagline | `Group` wrapping the existing inline SVG |
| Sign In / Sign Out anchor | `Button` variant `"default"` linking to `/login` or `POST /logout` |

### `CountrySelect`

| Current | Mantine |
|---|---|
| Native `<select>` | `Select` with `searchable` + `data` prop |
| Populated via `fetch('/countries')` | `useCountries` hook with `useEffect` |
| URL param `?country=XX` pre-selection | read from `useSearchParams` on mount |

### `SingleAddressLookup`

| Current | Mantine |
|---|---|
| `<input type="text">` + `<button>` in a flex row | `TextInput` + `Button` inside a `Group` |
| Result div with success/error class | `Alert` (color `"green"` / `"red"`) inside `Paper` |
| `renderPcodeFields` HTML builder | `PcodeResultCard` component rendering `Stack` of `Text` pairs |
| Enter key shortcut | `onKeyDown` prop on `TextInput` |

### `MapSection`

| Current | Mantine |
|---|---|
| Bare `<div id="map">` + Leaflet init | `MapContainer` from `react-leaflet` |
| `loadBoundaryLayer` + `L.geoJSON` | `GeoJSON` component from `react-leaflet` |
| Boundary level `<select>` | `Select` (`size="xs"`) inside a `Group` |
| Loading overlay div + spinner CSS | `Overlay` + `Loader` from Mantine |
| Map click marker | `useMapEvents` hook + `Marker` component |
| Map result panel below map | `PcodeResultCard` inside `Paper` with `mt="sm"` |

### `BatchUpload`

| Current | Mantine |
|---|---|
| Dashed drag-drop area | `Dropzone` from `@mantine/dropzone` |
| Format `<select>` | `SegmentedControl` (`CSV` / `XLSX`) |
| Output filename `<input>` | `TextInput` |
| Limit `<input type="number">` | `NumberInput` |
| Submit `<button>` | `Button` with `loading` prop |
| Indeterminate progress bar | `Progress` with `animated striped` |
| Stats grid (Total / Successful / Failed / Skipped) | `SimpleGrid` of `Paper` + `Text` |
| "Download Again" button | `Button` variant `"outline"` color `"green"` |
| Login prompt with dashed border | `Paper` with `withBorder` + `Alert` |

### `LoginPage`

| Current | Mantine |
|---|---|
| Centred card layout | `Center` > `Paper` with shadow + padding |
| Username field | `TextInput` via `useForm` |
| Password field | `PasswordInput` via `useForm` |
| Error flash | `Alert` color `"red"` |
| Submit | `Button` type `"submit"` + `loading` state |

Auth: POST to `/login` with `Content-Type: application/x-www-form-urlencoded`
(matching existing Flask handler). On 200 redirect response, navigate to `/` via
`window.location.href` (keeps cookie flow identical).

---

## Phase 4 — Auth Handling

The Flask backend uses server-side sessions. The SPA must:

1. On app boot, call `GET /health` (or a new `GET /api/me`) to check `logged_in`
   state and store it in a React context / lightweight state.
2. After a successful login POST, let Flask redirect to `/` — the SPA catches this
   as a full page load and re-checks auth state.
3. Logout: `GET /logout` triggers a full redirect as before.

No backend changes required for this approach.

> **Optional improvement**: add a `GET /api/me` endpoint returning `{"logged_in": true/false}`
> to avoid hijacking `/health` for auth checks.

---

## Phase 5 — Flask Integration (serving the built SPA)

### Development

Run Flask and Vite separately:

```bash
# Terminal 1
flask run --port 5001

# Terminal 2
cd frontend && npm run dev   # proxies /api/* → :5001
```

### Production

Vite outputs to `static/` (`build.outDir: '../static'`). Update Flask to serve the
SPA's `index.html` for all non-API routes:

```python
# In web_app.py — add after existing routes
@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_spa(path):
    """Serve the React SPA for any non-API route."""
    static_file = os.path.join(app.static_folder, path)
    if path and os.path.exists(static_file):
        return send_from_directory(app.static_folder, path)
    return send_from_directory(app.static_folder, "index.html")
```

Set `static_folder="static"` in the Flask app constructor (already the default).
Remove the old `render_template("index.html")` and `render_template("login.html")`
route handlers once the SPA handles those routes.

The login route (`/login`) can remain as a Flask form handler or become API-only
once the SPA takes over the login page.

---

## Phase 6 — Routing

Two client-side routes:

```
/          → MainPage  (country select, single lookup, map, batch upload)
/login     → LoginPage
```

Use `createBrowserRouter` (React Router v6). The Vite dev server is already
configured to fallback to `index.html`. Flask's `serve_spa` catch-all handles
this in production.

---

## Phase 7 — Migration Sequence (step-by-step)

| Step | Task | Notes |
|---|---|---|
| 1 | Scaffold `frontend/` with Vite + TS | `npm create vite@latest` |
| 2 | Install and configure Mantine + MantineProvider | Set theme: primary color `#4A90E2` → Mantine `blue` |
| 3 | Install react-leaflet, leaflet types | Fix leaflet CSS import in `main.tsx` |
| 4 | Create `api/types.ts` and `api/client.ts` | Typed fetch wrappers |
| 5 | Build `AppHeader` component | SVG logo preserved as-is |
| 6 | Build `CountrySelect` with `useCountries` hook | |
| 7 | Build `PcodeResultCard` — shared result renderer | Used by both lookup modes |
| 8 | Build `SingleAddressLookup` | |
| 9 | Build `MapSection` with react-leaflet | Boundary layer + level selector |
| 10 | Build `BatchUpload` with Mantine Dropzone | Logged-in gate via auth context |
| 11 | Build `LoginPage` with Mantine form | POST to Flask `/login` |
| 12 | Wire `MainPage` and `App.tsx` with router | |
| 13 | Add Vite proxy config + test dev flow | |
| 14 | Update Flask `serve_spa` catch-all | Add `send_from_directory` import |
| 15 | Update `Dockerfile` to run `npm run build` before Flask start | |
| 16 | Remove `templates/index.html` and `templates/login.html` | After SPA validated |
| 17 | Update `web_app.py` to remove Jinja2 routes | |

---

## Phase 8 — Dockerfile Updates

```dockerfile
# Build step
FROM node:20-alpine AS frontend-build
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build           # outputs to /app/static/

# Runtime step (existing Python image)
FROM python:3.11-slim
WORKDIR /app
COPY --from=frontend-build /app/static ./static
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["gunicorn", "web_app:app", "--bind", "0.0.0.0:5001"]
```

---

## Phase 9 — Testing Updates

- Existing pytest tests in `tests/` cover the Flask API — **no changes needed**.
- Add Vitest + `@testing-library/react` for component tests:
  - `CountrySelect` renders options from mocked API
  - `SingleAddressLookup` shows result on success, error alert on failure
  - `BatchUpload` progresses through upload states
  - `LoginPage` submits form and handles error response

```bash
npm install -D vitest @testing-library/react @testing-library/user-event \
               @testing-library/jest-dom jsdom
```

---

## Open Questions / Decisions

1. **Mantine theme colour**: use `blue` (closest to `#4A90E2`) or define a custom
   colour via `generateColors`.
2. **Login flow**: keep Flask redirect-based login (simplest, no backend changes)
   vs. move to JSON API login with cookie — recommend keeping redirect flow.
3. **`static_folder` conflict**: Flask currently uses `static/` for nothing; confirm
   there are no existing static assets before pointing Vite output there.
4. **react-leaflet CSS**: must import `leaflet/dist/leaflet.css` in `main.tsx` —
   include in `MantineProvider` or global styles.
5. **Map height**: currently `400px` desktop / `300px` tablet / `250px` mobile —
   use Mantine responsive `style` prop or CSS module.
