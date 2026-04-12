import { Button, Group, Text } from '@mantine/core';
import { KoboLogo } from './KoboLogo';
import { useAuth } from '../context/AuthContext';

export function AppHeader() {
  const { loggedIn } = useAuth();

  return (
    <Group
      justify="space-between"
      align="center"
      px="xl"
      py="md"
      style={{
        background: '#fff',
        borderBottom: '1px solid #e5e7eb',
      }}
    >
      <Group gap="sm" align="center">
        <KoboLogo width={110} />
        <Text size="sm" c="dimmed" fw={400}>
          P-Code Lookup
        </Text>
      </Group>

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
