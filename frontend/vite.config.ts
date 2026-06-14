import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
// Django dev server (manage.py runserver). All API routes are same-origin in
// production; the proxy is only for `vite dev`.
const BACKEND = 'http://localhost:8000'

const proxyRoutes = [
  '/countries',
  '/api',
  '/boundaries.geojson',
  '/secondary_boundaries.geojson',
  '/boundaries',
  '/geocode',
  '/geocode_single',
  '/reverse_geocode',
  '/xlsform',
  '/health',
]

export default defineConfig({
  root: __dirname,
  plugins: [react()],
  server: {
    proxy: {
      ...Object.fromEntries(
        proxyRoutes.map((route) => [route, { target: BACKEND, changeOrigin: true }])
      ),
    },
  },
  build: {
    outDir: path.resolve(__dirname, '../static'),
    emptyOutDir: true,
  },
})
