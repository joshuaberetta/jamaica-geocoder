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
}

interface ClickHandlerProps {
  country: string | null;
  onResult: (result: PcodeResult, lat: number, lon: number) => void;
}

/** Pans/zooms the map imperatively when mapCenter prop changes. Must be a child of MapContainer. */
function MapController({ center }: { center: { lat: number; lon: number; zoom: number } | null }) {
  const map = useMap();
  useEffect(() => {
    if (center) {
      map.setView([center.lat, center.lon], center.zoom);
    }
  }, [center, map]);
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

export function MapSection({ country, mapCenter }: Props) {
  const levels = useAvailableLevels(country);
  const [selectedLevel, setSelectedLevel] = useState<number>(2);
  const [geojson, setGeojson] = useState<FeatureCollection | null>(null);
  const [loadingBoundary, setLoadingBoundary] = useState(false);
  const [markerPos, setMarkerPos] = useState<[number, number] | null>(null);
  const [result, setResult] = useState<PcodeResult | null>(null);

  // Pick a sensible default level when available levels load
  useEffect(() => {
    if (!levels.length) return;
    const preferred = levels.includes(2) ? 2 : levels[levels.length - 1];
    setSelectedLevel(preferred);
  }, [levels]);

  // Load boundary GeoJSON whenever country or level changes
  useEffect(() => {
    if (!country) { setGeojson(null); return; }
    setLoadingBoundary(true);
    fetch(`/boundaries.geojson?country=${country}&level=${selectedLevel}`)
      .then((r) => r.ok ? r.json() : null)
      .then((data) => setGeojson(data))
      .catch(() => setGeojson(null))
      .finally(() => setLoadingBoundary(false));
  }, [country, selectedLevel]);

  const handleMapClick = (res: PcodeResult, lat: number, lon: number) => {
    setMarkerPos([lat, lon]);
    setResult(res);
  };

  const levelOptions = levels.map((l) => ({ value: String(l), label: `ADM${l}` }));

  return (
    <Paper withBorder p="md" radius="sm">
      <Stack gap="sm">
        <Text fw={500} size="lg">Select Point from Map</Text>
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

        <Box style={{ position: 'relative' }}>
          <MapContainer
            center={[10, 20]}
            zoom={2}
            style={{ height: 400, width: '100%', borderRadius: 4, border: '1px solid #d1d5da' }}
          >
            <MapController center={mapCenter} />
            <TileLayer
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              attribution="&copy; OpenStreetMap contributors"
              maxZoom={19}
            />
            {geojson && (
              <GeoJSON
                key={`${country}-${selectedLevel}`}
                data={geojson}
                style={{
                  color: '#3a7fc1',
                  weight: 1,
                  fillOpacity: 0.05,
                  fillColor: '#3a7fc1',
                }}
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

