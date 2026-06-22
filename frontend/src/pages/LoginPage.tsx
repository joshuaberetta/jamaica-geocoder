import { Alert, Button, Center, Paper, PasswordInput, Stack, Text, TextInput } from '@mantine/core';
import { useForm } from '@mantine/form';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { login } from '../api/auth';
import { useAuth } from '../context/AuthContext';

export function LoginPage() {
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();
  const { setLoggedIn } = useAuth();

  const form = useForm({
    initialValues: { username: '', password: '' },
    validate: {
      username: (v) => (v.trim() ? null : 'Username is required'),
      password: (v) => (v ? null : 'Password is required'),
    },
  });

  const handleSubmit = async (values: { username: string; password: string }) => {
    setLoading(true);
    setError(null);
    try {
      // Authenticate and start a session (sets the session cookie).
      await login(values.username, values.password);
      setLoggedIn(true);
      navigate('/');
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <Center style={{ minHeight: '100vh', background: '#f5f6f8', padding: 20 }}>
      <Paper withBorder p={48} radius="md" style={{ maxWidth: 420, width: '100%', boxShadow: '0 1px 4px rgba(0,0,0,0.06)' }}>
        <Stack align="center" gap="sm" mb="xl">
          <img src="/logo.svg" alt="Humanitarian Geocoder" style={{ width: 64, height: 64 }} />
          <Text fw={700} size="lg" c="#111827">Humanitarian Geocoder</Text>
        </Stack>

        <Text fw={700} size="xl" c="#111827" mb={4}>Sign In</Text>
        <Text size="sm" c="dimmed" mb="xl">
          Access batch geocoding features
        </Text>

        {error && (
          <Alert color="red" variant="light" mb="md">
            {error}
          </Alert>
        )}

        <form onSubmit={form.onSubmit(handleSubmit)}>
          <Stack gap="md">
            <TextInput
              label="Username"
              {...form.getInputProps('username')}
              autoComplete="username"
            />
            <PasswordInput
              label="Password"
              placeholder="••••••••"
              {...form.getInputProps('password')}
              autoComplete="current-password"
            />
            <Button type="submit" loading={loading} fullWidth>
              Sign In
            </Button>
          </Stack>
        </form>
      </Paper>
    </Center>
  );
}
