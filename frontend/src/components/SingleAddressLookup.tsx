import { Alert, Button, Group, Paper, Stack, TextInput, Text } from '@mantine/core';
import { useState } from 'react';
import { geocodeSingle } from '../api/client';
import type { PcodeResult } from '../api/types';
import { PcodeResultCard } from './PcodeResultCard';

interface Props {
  country: string | null;
  onResult?: (result: PcodeResult) => void;
}

export function SingleAddressLookup({ country, onResult }: Props) {
  const [address, setAddress] = useState('');
  const [result, setResult] = useState<PcodeResult | null>(null);
  const [loading, setLoading] = useState(false);

  const handleGeocode = async () => {
    const trimmed = address.trim();
    if (!trimmed) return;
    setLoading(true);
    setResult(null);
    try {
      const res = await geocodeSingle(trimmed, country ?? undefined);
      setResult(res);
      if (res.success) onResult?.(res);
    } catch (err) {
      setResult({ success: false, error: (err as Error).message });
    } finally {
      setLoading(false);
    }
  };

  return (
    <Paper withBorder p="md" radius="sm">
      <Stack gap="sm">
        <Text fw={500} size="lg">Single Address Lookup</Text>
        <Group gap="sm" align="flex-end">
          <TextInput
            style={{ flex: 1 }}
            placeholder="Enter address or GPS coordinates (e.g. '18.0179, -76.8099')"
            value={address}
            onChange={(e) => setAddress(e.currentTarget.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleGeocode()}
          />
          <Button loading={loading} onClick={handleGeocode}>
            Geocode
          </Button>
        </Group>

        {result && (
          result.success ? (
            <Alert color="green" variant="light">
              <PcodeResultCard result={result} />
            </Alert>
          ) : (
            <Alert color="red" variant="light">
              {result.error ?? 'Failed to geocode address'}
            </Alert>
          )
        )}
      </Stack>
    </Paper>
  );
}
