import { Button, Group, Stack, Text } from '@mantine/core';
import { KoboLogo } from './KoboLogo';
import { useAuth } from '../context/AuthContext';

export function AppHeader() {
  const { loggedIn } = useAuth();

  return (
    <Group
      justify="space-between"
      align="center"
      px="md"
      py="sm"
      style={{
        background: '#fff',
        boxShadow: '0 1px 3px rgba(0,0,0,0.1)',
        marginBottom: 24,
      }}
    >
      <Stack gap={4}>
        <Group gap="sm">
          <KoboLogo width={120} />
          <Text size="sm" c="dimmed">
            Humanitarian Geocoder
          </Text>
        </Group>
        <Text size="xs" c="dimmed" fs="italic" style={{ letterSpacing: '0.3px' }}>
          Where data meets purpose
        </Text>
      </Stack>

      {loggedIn ? (
        <Button
          component="a"
          href="/logout"
          variant="default"
          size="sm"
        >
          Sign Out
        </Button>
      ) : (
        <Button
          component="a"
          href="/login"
          variant="default"
          size="sm"
        >
          Sign In
        </Button>
      )}
    </Group>
  );
}
