import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const FLASK = 'http://localhost:5001'

const proxyRoutes = [
  '/countries',
  '/api',
  '/boundaries.geojson',
  '/geocode',
  '/geocode_single',
  '/reverse_geocode',
  '/logout',
  '/health',
]

export default defineConfig({
  root: __dirname,
  plugins: [react()],
  server: {
    proxy: {
      ...Object.fromEntries(
        proxyRoutes.map((route) => [route, { target: FLASK, changeOrigin: true }])
      ),
      // Only proxy POST /login to Flask (form submit). GET /login is handled
      // by the React SPA's LoginPage component.
      '/login': {
        target: FLASK,
        changeOrigin: true,
        bypass(req) {
          if (req.method !== 'POST') return req.url;
          return null;
        },
      },
    },
  },
  build: {
    outDir: path.resolve(__dirname, '../static'),
    emptyOutDir: true,
  },
})
