import {
  Alert,
  Button,
  NumberInput,
  Paper,
  Progress,
  SegmentedControl,
  SimpleGrid,
  Stack,
  Text,
  TextInput,
} from '@mantine/core';
import { Dropzone } from '@mantine/dropzone';
import { useState, useRef } from 'react';
import { geocodeBatch } from '../api/client';
import type { BatchStats } from '../api/types';
import { useAuth } from '../context/AuthContext';

interface Props {
  country: string | null;
}

function StatBox({ value, label, color }: { value: number; label: string; color: string }) {
  return (
    <Paper withBorder p="md" radius="sm" ta="center">
      <Text size="xl" fw={600} c={color}>
        {value}
      </Text>
      <Text size="xs" tt="uppercase" c="dimmed" style={{ letterSpacing: '0.5px' }}>
        {label}
      </Text>
    </Paper>
  );
}

function downloadFile(base64Data: string, filename: string, mimetype: string) {
  const byteChars = atob(base64Data);
  const arr = new Uint8Array(byteChars.length);
  for (let i = 0; i < byteChars.length; i++) arr[i] = byteChars.charCodeAt(i);
  const blob = new Blob([arr], { type: mimetype });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export function BatchUpload({ country }: Props) {
  const { loggedIn } = useAuth();
  const [file, setFile] = useState<File | null>(null);
  const [format, setFormat] = useState('xlsx');
  const [outputFilename, setOutputFilename] = useState('');
  const [limit, setLimit] = useState<number | string>('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [stats, setStats] = useState<BatchStats | null>(null);
  const lastDownload = useRef<{ fileData: string; filename: string; mimetype: string } | null>(null);

  if (!loggedIn) {
    return (
      <Paper withBorder p="xl" radius="sm" ta="center" style={{ borderStyle: 'dashed', borderWidth: 2 }}>
        <Stack align="center" gap="sm">
          <Text fw={500} size="lg">Sign In Required</Text>
          <Text size="sm" c="dimmed">
            Batch file processing requires authentication. Please sign in to upload and geocode
            multiple addresses.
          </Text>
          <Button component="a" href="/login">
            Sign In for Batch Processing
          </Button>
        </Stack>
      </Paper>
    );
  }

  const handleSubmit = async () => {
    if (!file) { setError('Please select a file to upload'); return; }
    setLoading(true);
    setError(null);
    setStats(null);

    const formData = new FormData();
    formData.append('file', file);
    formData.append('format', format);
    if (outputFilename) formData.append('output_filename', outputFilename);
    if (limit) formData.append('limit', String(limit));
    if (country) formData.append('country', country);

    try {
      const result = await geocodeBatch(formData);
      if (!result.success) throw new Error(result.error ?? 'Geocoding failed');
      lastDownload.current = { fileData: result.file_data, filename: result.filename, mimetype: result.mimetype };
      downloadFile(result.file_data, result.filename, result.mimetype);
      setStats(result.stats);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <Paper withBorder p="md" radius="sm">
      <Stack gap="md">
        <Text fw={500} size="lg">Batch File Upload</Text>

        <Dropzone
          onDrop={(files) => { setFile(files[0]); setStats(null); }}
          accept={{
            'text/csv': ['.csv'],
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
            'application/vnd.ms-excel': ['.xls'],
          }}
          maxFiles={1}
          maxSize={16 * 1024 * 1024}
        >
          <Stack align="center" justify="center" style={{ minHeight: 120 }} gap="xs">
            <Text size="xl">📄</Text>
            <Text size="sm" c="dimmed">
              {file ? `📎 ${file.name}` : 'Click to upload or drag and drop'}
            </Text>
            <Text size="xs" c="dimmed">CSV or Excel (.csv, .xlsx, .xls) — max 16 MB</Text>
          </Stack>
        </Dropzone>

        <SimpleGrid cols={{ base: 1, sm: 3 }} spacing="md">
          <Stack gap={4}>
            <Text size="sm" fw={500}>Output Format</Text>
            <SegmentedControl
              data={[
                { label: 'CSV', value: 'csv' },
                { label: 'Excel (XLSX)', value: 'xlsx' },
              ]}
              value={format}
              onChange={setFormat}
            />
          </Stack>

          <TextInput
            label="Output Filename (optional)"
            placeholder="geocoded_addresses"
            value={outputFilename}
            onChange={(e) => setOutputFilename(e.currentTarget.value)}
          />

          <NumberInput
            label="Limit (optional)"
            placeholder="All addresses"
            min={1}
            value={limit}
            onChange={setLimit}
          />
        </SimpleGrid>

        {loading && (
          <Stack gap={4}>
            <Progress value={100} animated striped size="sm" />
            <Text size="xs" c="dimmed" ta="center">Uploading and geocoding addresses…</Text>
          </Stack>
        )}

        {error && (
          <Alert color="red" variant="light">
            {error}
          </Alert>
        )}

        {stats && (
          <Stack gap="sm">
            <Text fw={500}>✅ Geocoding Complete!</Text>
            <SimpleGrid cols={{ base: 2, sm: 4 }} spacing="sm">
              <StatBox value={stats.total} label="Total" color="blue" />
              <StatBox value={stats.successful} label="Successful" color="green" />
              <StatBox value={stats.failed} label="Failed" color="orange" />
              <StatBox value={stats.skipped} label="Skipped" color="gray" />
            </SimpleGrid>
            <Text size="sm" c="dimmed">Your file has been downloaded automatically.</Text>
            <Button
              variant="outline"
              color="green"
              onClick={() => lastDownload.current && downloadFile(lastDownload.current.fileData, lastDownload.current.filename, lastDownload.current.mimetype)}
            >
              Download Again
            </Button>
          </Stack>
        )}

        <Button loading={loading} onClick={handleSubmit} disabled={!file}>
          Geocode Addresses
        </Button>

        <Paper withBorder p="md" radius="sm" bg="gray.0">
          <Stack gap={4}>
            <Text size="sm" fw={500}>📋 File Format Requirements</Text>
            <ul style={{ paddingLeft: 20, margin: 0 }}>
              <li><Text size="sm" c="dimmed" component="span">Accepts CSV (semicolon-separated) or Excel (.xlsx, .xls)</Text></li>
              <li><Text size="sm" c="dimmed" component="span">Required column: <code>address</code></Text></li>
              <li><Text size="sm" c="dimmed" component="span">Optional columns: <code>date</code>, <code>name</code>, <code>hot_meals</code></Text></li>
              <li><Text size="sm" c="dimmed" component="span">Date format: <code>m/d</code> (converted to yyyy-mm-dd)</Text></li>
            </ul>
          </Stack>
        </Paper>
      </Stack>
    </Paper>
  );
}
