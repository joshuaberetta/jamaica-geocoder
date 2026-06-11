import { Group, Stack, Text } from '@mantine/core';
import type { PcodeResult } from '../api/types';

interface Props {
  result: PcodeResult;
}

function Row({ label, value }: { label: string; value: string | number }) {
  return (
    <Group gap="xs" align="baseline" wrap="nowrap">
      <Text size="sm" fw={600} style={{ minWidth: 160, flexShrink: 0 }}>
        {label}:
      </Text>
      <Text size="sm">{String(value)}</Text>
    </Group>
  );
}

export function PcodeResultCard({ result }: Props) {
  const rows: { label: string; value: string | number }[] = [];

  if (result.latitude !== undefined)
    rows.push({ label: 'Latitude', value: result.latitude.toFixed(6) });
  if (result.longitude !== undefined)
    rows.push({ label: 'Longitude', value: result.longitude.toFixed(6) });
  if (result.address) rows.push({ label: 'Address', value: result.address });
  if (result.confidence) rows.push({ label: 'Confidence', value: result.confidence });
  if (result.country) rows.push({ label: 'Country', value: result.country });

  for (let n = 0; n <= 4; n++) {
    const pcode = result[`adm${n}_pcode` as keyof PcodeResult] as string | undefined;
    const name = result[`adm${n}_name` as keyof PcodeResult] as string | undefined;
    if (pcode) rows.push({ label: `ADM${n} P-Code`, value: pcode });
    if (name) rows.push({ label: `ADM${n} Name`, value: name });
  }

  if (result.health_zone_name)
    rows.push({ label: 'Health Zone', value: result.health_zone_name });
  if (result.health_zone_dhis2)
    rows.push({ label: 'Health Zone DHIS2', value: result.health_zone_dhis2 });

  if (!rows.length) {
    return <Text size="sm">No P-code data found.</Text>;
  }

  return (
    <Stack gap={4}>
      {rows.map((r) => (
        <Row key={r.label} label={r.label} value={r.value} />
      ))}
    </Stack>
  );
}
