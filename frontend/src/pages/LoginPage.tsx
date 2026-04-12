import { Alert, Button, Center, Paper, PasswordInput, Stack, Text, TextInput, Title } from '@mantine/core';
import { useForm } from '@mantine/form';
import { useState } from 'react';
import { KoboLogo } from '../components/KoboLogo';

export function LoginPage() {
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

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
      const body = new URLSearchParams();
      body.append('username', values.username);
      body.append('password', values.password);

      const res = await fetch('/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: body.toString(),
      });

      if (res.ok) {
        // Flask redirects to / on success; confirm auth then navigate
        window.location.href = '/';
        return;
      }

      // 401 = invalid credentials
      setError('Invalid username or password');
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <Center style={{ minHeight: '100vh', background: '#f4f5f7', padding: 20 }}>
      <Paper withBorder shadow="sm" p={48} radius="sm" style={{ maxWidth: 420, width: '100%' }}>
        <Stack align="center" gap="xs" mb="xl">
          <KoboLogo width={180} />
          <Text size="xs" c="dimmed" fs="italic" style={{ letterSpacing: '0.5px' }}>
            Where data meets purpose
          </Text>
        </Stack>

        <Title order={2} ta="center" mb={4} fw={500}>
          Sign In
        </Title>
        <Text size="sm" c="dimmed" ta="center" mb="xl">
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
              placeholder="admin"
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
