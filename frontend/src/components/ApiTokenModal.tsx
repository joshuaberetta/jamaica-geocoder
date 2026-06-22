import {
  Alert,
  Button,
  CopyButton,
  Group,
  Modal,
  Stack,
  Text,
  TextInput,
  Tooltip,
} from '@mantine/core';
import { useEffect, useState } from 'react';
import { getApiToken, rotateApiToken } from '../api/auth';

interface Props {
  opened: boolean;
  onClose: () => void;
}

// Shows the logged-in user's API token (for headless/scripted access) with
// copy and regenerate actions. The token is fetched only when the modal opens.
export function ApiTokenModal({ opened, onClose }: Props) {
  const [token, setToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmingRotate, setConfirmingRotate] = useState(false);

  // Fetch the token whenever the modal opens.
  useEffect(() => {
    if (!opened) return;
    setError(null);
    setConfirmingRotate(false);
    setLoading(true);
    getApiToken()
      .then(setToken)
      .catch((e) => setError((e as Error).message))
      .finally(() => setLoading(false));
  }, [opened]);

  const handleRotate = () => {
    setLoading(true);
    setError(null);
    rotateApiToken()
      .then((t) => {
        setToken(t);
        setConfirmingRotate(false);
      })
      .catch((e) => setError((e as Error).message))
      .finally(() => setLoading(false));
  };

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title="Your API Token"
      centered
    >
      <Stack gap="md">
        <Text size="sm" c="dimmed">
          Use this token for scripted or headless access by sending it as an{' '}
          <Text span ff="monospace" size="sm">
            Authorization: Token &lt;token&gt;
          </Text>{' '}
          header. Keep it secret — it grants full access to your account.
        </Text>

        {error && (
          <Alert color="red" variant="light">
            {error}
          </Alert>
        )}

        <Group gap="xs" wrap="nowrap">
          <TextInput
            value={loading ? 'Loading…' : token ?? ''}
            readOnly
            style={{ flex: 1 }}
            ff="monospace"
          />
          <CopyButton value={token ?? ''} timeout={1500}>
            {({ copied, copy }) => (
              <Tooltip label={copied ? 'Copied' : 'Copy'} withArrow>
                <Button onClick={copy} disabled={!token} variant="default">
                  {copied ? 'Copied' : 'Copy'}
                </Button>
              </Tooltip>
            )}
          </CopyButton>
        </Group>

        {confirmingRotate ? (
          <Alert color="orange" variant="light">
            <Stack gap="xs">
              <Text size="sm">
                Regenerating invalidates the current token immediately. Any scripts using it
                will stop working until updated.
              </Text>
              <Group gap="xs">
                <Button color="orange" size="xs" loading={loading} onClick={handleRotate}>
                  Regenerate
                </Button>
                <Button variant="default" size="xs" onClick={() => setConfirmingRotate(false)}>
                  Cancel
                </Button>
              </Group>
            </Stack>
          </Alert>
        ) : (
          <Group justify="flex-end">
            <Button
              variant="subtle"
              color="orange"
              size="sm"
              disabled={!token}
              onClick={() => setConfirmingRotate(true)}
            >
              Regenerate token
            </Button>
          </Group>
        )}
      </Stack>
    </Modal>
  );
}
