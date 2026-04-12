import { Alert, Box, Loader, Overlay, Paper, Select, Stack, Text } from '@mantine/core';
import { useEffect, useState } from 'react';
import { MapContainer, TileLayer, GeoJSON, Marker, useMapEvents, useMap } from 'react-leaflet';
import L from 'leaflet';
import type { FeatureCollection } from 'geojson';
import { reverseGeocode } from '../api/client';
import type { PcodeResult } from '../api/types';
import { useAvailableLevels } from '../hooks/useAvailableLevels';
import { PcodeResultCard } from './PcodeResultCard';

// Fix leaflet default marker icons in Webpack/Vite
delete (L.Icon.Default.prototype as unknown as Record<string, unknown>)._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png',
  iconUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
  shadowUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png',
});

interface Props {
  country: string | null;
  mapCenter: { lat: number; lon: number; zoom: number } | null;
  isVisible?: boolean;
}

interface ClickHandlerProps {
  country: string | null;
  onResult: (result: PcodeResult, lat: number, lon: number) => void;
}

/**
 * Single component that handles both resize correction and bounds fitting.
 * invalidateSize() must happen before fitBounds(), and fitBounds() must be
 * deferred via requestAnimationFrame so the browser has had a chance to
 * apply the new container dimensions after display:none → display:block.
 */
function MapViewManager({ geojson, isVisible }: { geojson: FeatureCollection | null; isVisible: boolean }) {
  const map = useMap();
  useEffect(() => {
    if (!isVisible) return;
    map.invalidateSize();
    if (!geojson || !geojson.features.length) return;
    const raf = requestAnimationFrame(() => {
      try {
        const bounds = L.geoJSON(geojson).getBounds();
        if (bounds.isValid()) map.fitBounds(bounds, { padding: [20, 20] });
      } catch {
        // ignore malformed geometries
      }
    });
    return () => cancelAnimationFrame(raf);
  }, [geojson, isVisible, map]);
  return null;
}

function ClickHandler({ country, onResult }: ClickHandlerProps) {
  useMapEvents({
    click: async (e) => {
      const { lat, lng } = e.latlng;
      try {
        const result = await reverseGeocode(lat, lng, country ?? undefined);
        onResult(result, lat, lng);
      } catch (err) {
        onResult({ success: false, error: (err as Error).message }, lat, lng);
      }
    },
  });
  return null;
}

export function MapSection({ country, mapCenter, isVisible = true }: Props) {
  const levels = useAvailableLevels(country);
  const [selectedLevel, setSelectedLevel] = useState<number>(2);
  const [geojson, setGeojson] = useState<FeatureCollection | null>(null);
  const [loadingBoundary, setLoadingBoundary] = useState(false);
  const [markerPos, setMarkerPos] = useState<[number, number] | null>(null);
  const [result, setResult] = useState<PcodeResult | null>(null);

  // Pick a sensible default level when the available levels for a country load.
  useEffect(() => {
    if (!levels.length) return;
    const preferred = levels.includes(2) ? 2 : levels[levels.length - 1];
    setSelectedLevel(preferred);
  }, [levels]);

  // Load boundary GeoJSON whenever country or level changes.
  // Clears geojson immediately so the old layer is never visible alongside the new one.
  // Uses AbortController so stale in-flight requests are cancelled when deps change.
  useEffect(() => {
    setGeojson(null);
    if (!country) return;
    const controller = new AbortController();
    setLoadingBoundary(true);
    fetch(`/boundaries.geojson?country=${country}&level=${selectedLevel}`, { signal: controller.signal })
      .then((r) => r.ok ? r.json() : null)
      .then((data) => { if (!controller.signal.aborted) setGeojson(data); })
      .catch((err) => { if (err.name !== 'AbortError') setGeojson(null); })
      .finally(() => { if (!controller.signal.aborted) setLoadingBoundary(false); });
    return () => controller.abort();
  }, [country, selectedLevel]);

  const handleMapClick = (res: PcodeResult, lat: number, lon: number) => {
    setMarkerPos([lat, lon]);
    setResult(res);
  };

  const levelOptions = levels.map((l) => ({ value: String(l), label: `ADM${l}` }));

  return (
    <Paper withBorder p="md" radius="sm">
      <Stack gap="sm">
        <Text size="sm" c="dimmed">
          Click anywhere on the map to get P-code information for that location.
        </Text>

        {levelOptions.length > 0 && (
          <Select
            label="Boundary level"
            data={levelOptions}
            value={String(selectedLevel)}
            onChange={(v) => v && setSelectedLevel(Number(v))}
            style={{ maxWidth: 180 }}
          />
        )}

        <Box style={{ position: 'relative', zIndex: 0 }}>
          <MapContainer
            center={mapCenter ? [mapCenter.lat, mapCenter.lon] : [10, 20]}
            zoom={mapCenter?.zoom ?? 2}
            style={{ height: 400, width: '100%', borderRadius: 4, border: '1px solid #d1d5da' }}
          >
            <MapViewManager geojson={geojson} isVisible={isVisible} />
            <TileLayer
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              attribution="&copy; OpenStreetMap contributors"
              maxZoom={19}
            />
            {geojson && (
              <GeoJSON
                key={`${country}-${selectedLevel}`}
                data={geojson}
                style={{ color: '#3a7fc1', weight: 1, fillOpacity: 0.05, fillColor: '#3a7fc1' }}
              />
            )}
            {markerPos && <Marker position={markerPos} />}
            <ClickHandler country={country} onResult={handleMapClick} />
          </MapContainer>

          {loadingBoundary && (
            <Overlay
              style={{ borderRadius: 4, display: 'flex', flexDirection: 'column', gap: 12, alignItems: 'center', justifyContent: 'center' }}
              blur={2}
              backgroundOpacity={0.4}
            >
              <Loader size="md" />
              <Text size="sm" fw={500}>Loading boundaries…</Text>
            </Overlay>
          )}
        </Box>

        {result && (
          result.success ? (
            <Alert color="green" variant="light">
              <PcodeResultCard result={result} />
            </Alert>
          ) : (
            <Alert color="red" variant="light">
              {result.error ?? 'Point outside known boundaries'}
            </Alert>
          )
        )}
      </Stack>
    </Paper>
  );
}
