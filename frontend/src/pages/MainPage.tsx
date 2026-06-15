import { Anchor, Button, Container, Group, Paper, Stack, Tabs, Text } from '@mantine/core';
import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { BatchUpload } from '../components/BatchUpload';
import { BoundaryCsvLists } from '../components/BoundaryCsvLists';
import { CountrySelect } from '../components/CountrySelect';
import { MapSection } from '../components/MapSection';
import { SingleAddressLookup } from '../components/SingleAddressLookup';
import { XlsFormDownload } from '../components/XlsFormDownload';
import { useAuth } from '../context/AuthContext';
import { useCountries } from '../hooks/useCountries';
import type { Country } from '../api/types';

function KoboFooterIcon() {
  return (
    <svg viewBox="0 0 107 159" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ width: 16, height: 16, verticalAlign: 'middle', marginRight: 4 }}>
      <path d="M86.1382 106.78V122.26C86.1146 126.382 84.4666 130.329 81.5517 133.244C78.6369 136.159 74.6903 137.807 70.5682 137.83H36.9082C32.7861 137.807 28.8395 136.159 25.9247 133.244C23.0098 130.329 21.3618 126.382 21.3382 122.26V36.0401C21.3618 31.918 23.0098 27.9714 25.9247 25.0566C28.8395 22.1417 32.7861 20.4937 36.9082 20.4701H70.5682C74.6903 20.4937 78.6369 22.1417 81.5517 25.0566C84.4666 27.9714 86.1146 31.918 86.1382 36.0401V38.1101C89.0551 37.2073 92.0852 36.7224 95.1382 36.6701C98.8944 36.6783 102.617 37.3801 106.118 38.7401V36.0401C106.118 26.4923 102.325 17.3356 95.574 10.5843C88.8227 3.83298 79.666 0.0401306 70.1182 0.0401306H36.9082C27.3604 0.0401306 18.2037 3.83298 11.4524 10.5843C4.70105 17.3356 0.908203 26.4923 0.908203 36.0401V122.26C0.908203 131.808 4.70105 140.965 11.4524 147.716C18.2037 154.467 27.3604 158.26 36.9082 158.26H70.5682C80.116 158.26 89.2727 154.467 96.0241 147.716C102.775 140.965 106.568 131.808 106.568 122.26V83.2901L86.1382 106.78Z" fill="#2095F3"/>
      <path d="M69.6682 102.01L105.668 60.3401C106.24 59.7666 106.561 58.9898 106.561 58.1801C106.561 57.3704 106.24 56.5937 105.668 56.0201C104.148 54.687 102.379 53.6685 100.462 53.0234C98.5462 52.3782 96.5211 52.1193 94.5041 52.2616C92.4872 52.4039 90.5185 52.9445 88.7118 53.8522C86.9051 54.76 85.2963 56.0168 83.9782 57.5501L61.6582 83.2901C61.54 83.4242 61.3946 83.5316 61.2316 83.6051C61.0687 83.6787 60.892 83.7167 60.7132 83.7167C60.5345 83.7167 60.3578 83.6787 60.1948 83.6051C60.0319 83.5316 59.8865 83.4242 59.7682 83.2901L51.3982 73.0301C50.9928 72.5704 50.4943 72.2023 49.9356 71.9501C49.377 71.6979 48.7711 71.5675 48.1582 71.5675C47.5453 71.5675 46.9394 71.6979 46.3808 71.9501C45.8222 72.2023 45.3236 72.5704 44.9182 73.0301C42.3473 75.7498 40.8487 79.3087 40.6998 83.0482C40.5508 86.7878 41.7617 90.4546 44.1082 93.3701L50.9482 101.83C52.084 103.205 53.5064 104.315 55.116 105.082C56.7255 105.85 58.4833 106.256 60.2664 106.273C62.0494 106.29 63.8147 105.918 65.4387 105.181C67.0627 104.445 68.5062 103.363 69.6682 102.01Z" fill="#2095F3"/>
    </svg>
  );
}

export function MainPage() {
  const [selectedCountry, setSelectedCountry] = useState<Country | null>(null);
  const [mapCenter, setMapCenter] = useState<{ lat: number; lon: number; zoom: number } | null>(null);
  const [activeTab, setActiveTab] = useState<string>('map');
  const [searchParams] = useSearchParams();
  const { countries } = useCountries();
  const { loggedIn, logout } = useAuth();
  const navigate = useNavigate();

  // Pre-select country from ?country= URL param (matches ISO2, ISO3, or key, case-insensitive)
  useEffect(() => {
    const param = searchParams.get('country')?.toLowerCase();
    if (!param || countries.length === 0 || selectedCountry) return;
    const match = countries.find(
      (c) => c.code.toLowerCase() === param || c.iso3.toLowerCase() === param || c.key === param
    );
    if (match) handleCountryChange(match);
  }, [countries, searchParams]);

  const handleCountryChange = (country: Country | null) => {
    setSelectedCountry(country);
    if (country?.map_center) setMapCenter(country.map_center);
  };

  return (
    <div style={{ background: '#f5f6f8', minHeight: '100vh', paddingBottom: 48 }}>
      <Container size="md" pt="xl" pb="xl">
        <Paper withBorder p="xl" radius="md" style={{ background: '#fff' }}>
          <Stack gap="xl">
          <Group justify="space-between" align="flex-start" wrap="nowrap">
            <div>
              <Text size="xl" fw={700} c="#111827" mb={4}>Humanitarian Geocoder</Text>
              <Text size="sm" c="dimmed">
                Enter a single address or upload a CSV file with addresses to geocode and match to administrative boundaries.
              </Text>
            </div>
            <Button
              onClick={() => {
                if (loggedIn) {
                  logout();
                } else {
                  navigate('/login');
                }
              }}
              variant="default"
              size="sm"
              style={{ flexShrink: 0 }}
            >
              {loggedIn ? 'Sign Out' : 'Sign In'}
            </Button>
          </Group>

          <Tabs value={activeTab} onChange={(v) => v && setActiveTab(v)} variant="outline">
            <Tabs.List>
              <Tabs.Tab value="map">Map Picker</Tabs.Tab>
              <Tabs.Tab value="single">Single Lookup</Tabs.Tab>
              <Tabs.Tab value="batch">Batch Processing</Tabs.Tab>
              <Tabs.Tab value="csv">Boundary CSVs</Tabs.Tab>
            </Tabs.List>

            <Tabs.Panel value="single" pt="md">
              <SingleAddressLookup country={null} />
            </Tabs.Panel>

            {/* MapSection rendered outside Tabs.Panel so it is never unmounted — Leaflet
                errors when its container DOM node is reused after being destroyed. */}
            <div style={{ display: activeTab === 'map' ? 'block' : 'none', paddingTop: 16 }}>
              <Group align="flex-end" gap="sm" wrap="nowrap">
                <div style={{ flex: 1 }}>
                  <CountrySelect value={selectedCountry?.code ?? null} onChange={handleCountryChange} />
                </div>
                <XlsFormDownload country={selectedCountry?.code ?? null} />
              </Group>
              <div style={{ marginTop: 16 }}>
                <MapSection
                  country={selectedCountry?.code ?? null}
                  mapCenter={mapCenter}
                  isVisible={activeTab === 'map'}
                />
              </div>
            </div>

            <Tabs.Panel value="batch" pt="md">
              <BatchUpload country={null} />
            </Tabs.Panel>

            <Tabs.Panel value="csv" pt="md">
              <Stack gap="md">
                <CountrySelect value={selectedCountry?.code ?? null} onChange={handleCountryChange} />
                <BoundaryCsvLists country={selectedCountry?.code ?? null} />
              </Stack>
            </Tabs.Panel>
          </Tabs>

          </Stack>
        </Paper>

        <Group justify="center" mt="lg" style={{ paddingTop: 8 }}>
            <Text size="xs" c="dimmed">
              <KoboFooterIcon />
              Built by{' '}
              <Anchor href="https://www.kobo.ngo/" target="_blank" size="xs">
                Kobo
              </Anchor>
              {' | '}
              <Anchor
                href="https://github.com/kobotoolbox/geocoder/issues/new/choose"
                target="_blank"
                size="xs"
              >
                Report an issue
              </Anchor>
            </Text>
        </Group>
      </Container>
    </div>
  );
}
