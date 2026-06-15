import {
  ActionIcon,
  Anchor,
  Badge,
  Button,
  CopyButton,
  Divider,
  Group,
  Paper,
  Select,
  Stack,
  Text,
  TextInput,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useEffect, useMemo, useState } from 'react';
import {
  addBoundaryLanguage,
  createBoundaryProject,
  deleteBoundaryLanguage,
  deleteBoundaryProject,
  fetchBoundaryProject,
  fetchBoundaryProjects,
  updateBoundaryProject,
} from '../api/client';
import type { BoundaryCsvProject } from '../api/types';
import { useAuth } from '../context/AuthContext';
import { useAvailableLevels } from '../hooks/useAvailableLevels';

interface Props {
  country: string | null;
}

/** Slugify a project name for the URL (lowercase, spaces -> -, strip the rest). */
function slugify(name: string): string {
  return name
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

// Translation columns are XLSForm headers of the form `label::<suffix>`, e.g.
// `label::English (en)`. The UI only takes the suffix; we add/strip the prefix.
const LABEL_PREFIX = 'label::';

/** Turn a translation suffix into a full header. Empty suffix -> plain "label". */
function toHeader(suffix: string): string {
  const s = suffix.trim();
  return s ? `${LABEL_PREFIX}${s}` : 'label';
}

/** Strip the `label::` prefix for display; show full header otherwise. */
function toSuffix(header: string): string {
  return header.startsWith(LABEL_PREFIX) ? header.slice(LABEL_PREFIX.length) : header;
}

function CsvUrlRow({ label, path }: { label: string; path: string }) {
  const url = window.location.origin + path;
  return (
    <Group justify="space-between" wrap="nowrap" gap="xs">
      <Group gap="xs" wrap="nowrap" style={{ minWidth: 0 }}>
        <Badge variant="light" radius="sm">{label}</Badge>
        <Anchor href={path} target="_blank" size="sm" truncate>
          {path}
        </Anchor>
      </Group>
      <CopyButton value={url}>
        {({ copied, copy }) => (
          <Button size="xs" variant={copied ? 'filled' : 'default'} onClick={copy}>
            {copied ? 'Copied' : 'Copy'}
          </Button>
        )}
      </CopyButton>
    </Group>
  );
}

export function BoundaryCsvLists({ country }: Props) {
  const { loggedIn } = useAuth();
  const levels = useAvailableLevels(country);

  const [projects, setProjects] = useState<BoundaryCsvProject[]>([]);
  const [selectedSlug, setSelectedSlug] = useState<string | null>(null);
  const [detail, setDetail] = useState<BoundaryCsvProject | null>(null);
  const [newProjectName, setNewProjectName] = useState('');
  const [newSuffix, setNewSuffix] = useState('');
  const [labelSuffix, setLabelSuffix] = useState('');
  const [busy, setBusy] = useState(false);

  // Load the user's projects once signed in.
  useEffect(() => {
    if (!loggedIn) {
      setProjects([]);
      setSelectedSlug(null);
      return;
    }
    fetchBoundaryProjects()
      .then((ps) => setProjects(ps))
      .catch((e) => notifications.show({ color: 'red', message: (e as Error).message }));
  }, [loggedIn]);

  // Load the selected project's detail (with csv_urls for the current country).
  useEffect(() => {
    if (!selectedSlug) {
      setDetail(null);
      return;
    }
    fetchBoundaryProject(selectedSlug, country ?? undefined)
      .then((d) => {
        setDetail(d);
        setLabelSuffix(toSuffix(d.label_column_name === 'label' ? '' : d.label_column_name));
      })
      .catch((e) => notifications.show({ color: 'red', message: (e as Error).message }));
  }, [selectedSlug, country, projects]);

  const reloadDetail = () => {
    if (!selectedSlug) return;
    fetchBoundaryProject(selectedSlug, country ?? undefined).then(setDetail).catch(() => {});
  };

  const handleCreate = async () => {
    const name = newProjectName.trim();
    if (!name) return;
    setBusy(true);
    try {
      const created = await createBoundaryProject(name, slugify(name));
      setProjects((ps) => [created, ...ps]);
      setSelectedSlug(created.slug);
      setNewProjectName('');
      notifications.show({ color: 'green', message: `Created “${created.name}”` });
    } catch (e) {
      notifications.show({ color: 'red', message: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  const handleDeleteProject = async () => {
    if (!detail) return;
    setBusy(true);
    try {
      await deleteBoundaryProject(detail.slug);
      setProjects((ps) => ps.filter((p) => p.slug !== detail.slug));
      setSelectedSlug(null);
      notifications.show({ color: 'gray', message: 'Project deleted' });
    } catch (e) {
      notifications.show({ color: 'red', message: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  const handleAddLanguage = async () => {
    if (!detail) return;
    const suffix = newSuffix.trim();
    if (!suffix) return;
    setBusy(true);
    try {
      await addBoundaryLanguage(detail.slug, toHeader(suffix));
      setNewSuffix('');
      reloadDetail();
    } catch (e) {
      notifications.show({ color: 'red', message: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  const handleSaveLabel = async () => {
    if (!detail) return;
    setBusy(true);
    try {
      await updateBoundaryProject(detail.slug, { label_column_name: toHeader(labelSuffix) });
      reloadDetail();
      notifications.show({ color: 'green', message: 'Label column updated' });
    } catch (e) {
      notifications.show({ color: 'red', message: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  const handleRemoveLanguage = async (id: number) => {
    if (!detail) return;
    setBusy(true);
    try {
      await deleteBoundaryLanguage(detail.slug, id);
      reloadDetail();
    } catch (e) {
      notifications.show({ color: 'red', message: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  // Default (no-translation) CSV links derived from the available levels.
  const defaultUrls = useMemo(() => {
    if (!country) return [];
    return levels.map((l) => ({
      label: `Level ${l}`,
      path: `/boundaries/${country}/${l}.csv`,
    }));
  }, [country, levels]);

  if (!country) {
    return (
      <Paper withBorder p="md" radius="sm">
        <Text size="sm" c="dimmed">Select a country to get its admin-boundary CSV links.</Text>
      </Paper>
    );
  }

  return (
    <Paper withBorder p="md" radius="sm">
      <Stack gap="md">
        <div>
          <Text fw={500} size="lg">Admin-Boundary CSV Lists</Text>
          <Text size="sm" c="dimmed">
            Per-level CSVs of {country} admin boundaries (the XLSForm choices), ready to use as
            KoboToolbox external choice lists. URLs end in <code>.csv</code>.
          </Text>
        </div>

        {/* Default, no-auth links */}
        <Stack gap="xs">
          <Text size="sm" fw={500}>Default (no translation columns)</Text>
          {defaultUrls.length === 0 ? (
            <Text size="sm" c="dimmed">No admin levels available for this country.</Text>
          ) : (
            defaultUrls.map((u) => <CsvUrlRow key={u.path} label={u.label} path={u.path} />)
          )}
        </Stack>

        <Divider label="Project translation columns" labelPosition="center" />

        {!loggedIn ? (
          <Text size="sm" c="dimmed">
            <Anchor href="/login">Sign in</Anchor> to create a project and append translation
            columns (e.g. <code>label::Spanish (es)</code>) to your CSVs.
          </Text>
        ) : (
          <Stack gap="md">
            <Group align="flex-end" gap="sm">
              <Select
                label="Project"
                placeholder="Select a project…"
                data={projects.map((p) => ({ value: p.slug, label: p.name }))}
                value={selectedSlug}
                onChange={setSelectedSlug}
                style={{ flex: 1 }}
                clearable
              />
              <TextInput
                label="New project"
                placeholder="My survey"
                value={newProjectName}
                onChange={(e) => setNewProjectName(e.currentTarget.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleCreate()}
              />
              <Button onClick={handleCreate} loading={busy} disabled={!newProjectName.trim()}>
                Create
              </Button>
            </Group>

            {detail && (
              <Stack gap="sm">
                <Group justify="space-between">
                  <Text fw={500}>{detail.name}</Text>
                  <Button variant="subtle" color="red" size="xs" onClick={handleDeleteProject} loading={busy}>
                    Delete project
                  </Button>
                </Group>

                {/* Primary label column */}
                <Stack gap={4}>
                  <Text size="sm" fw={500}>Primary label column</Text>
                  <Text size="xs" c="dimmed">
                    Make the main label column a translation. Leave blank for a plain{' '}
                    <code>label</code> header.
                  </Text>
                  <Group align="flex-end" gap="sm" mt={4}>
                    <TextInput
                      placeholder="English (en)"
                      leftSection={<Text size="sm" c="dimmed">label::</Text>}
                      leftSectionWidth={56}
                      value={labelSuffix}
                      onChange={(e) => setLabelSuffix(e.currentTarget.value)}
                      onKeyDown={(e) => e.key === 'Enter' && handleSaveLabel()}
                      style={{ flex: 1 }}
                    />
                    <Button
                      variant="default"
                      onClick={handleSaveLabel}
                      loading={busy}
                      disabled={toHeader(labelSuffix) === detail.label_column_name}
                    >
                      Save
                    </Button>
                  </Group>
                </Stack>

                {/* Translation columns */}
                <Stack gap={4}>
                  <Text size="sm" fw={500}>Additional translation columns</Text>
                  {detail.languages.length === 0 ? (
                    <Text size="sm" c="dimmed">
                      None yet. Each adds a <code>label::…</code> column that duplicates the label.
                    </Text>
                  ) : (
                    <Group gap="xs">
                      {detail.languages.map((lang) => (
                        <Badge
                          key={lang.id}
                          variant="light"
                          radius="sm"
                          rightSection={
                            <ActionIcon
                              size="xs"
                              variant="transparent"
                              color="red"
                              onClick={() => handleRemoveLanguage(lang.id)}
                              aria-label={`Remove ${lang.header}`}
                            >
                              ✕
                            </ActionIcon>
                          }
                        >
                          {lang.header}
                        </Badge>
                      ))}
                    </Group>
                  )}
                  <Group align="flex-end" gap="sm" mt={4}>
                    <TextInput
                      label="Add translation"
                      placeholder="Spanish (es)"
                      leftSection={<Text size="sm" c="dimmed">label::</Text>}
                      leftSectionWidth={56}
                      value={newSuffix}
                      onChange={(e) => setNewSuffix(e.currentTarget.value)}
                      onKeyDown={(e) => e.key === 'Enter' && handleAddLanguage()}
                      style={{ flex: 1 }}
                    />
                    <Button onClick={handleAddLanguage} loading={busy} disabled={!newSuffix.trim()}>
                      Add
                    </Button>
                  </Group>
                </Stack>

                {/* Project CSV links */}
                <Stack gap="xs">
                  <Text size="sm" fw={500}>CSV links for {country}</Text>
                  {detail.csv_urls && detail.csv_urls.length > 0 ? (
                    detail.csv_urls.map((u) => (
                      <CsvUrlRow
                        key={u.url}
                        label={u.level === 'health_zone' ? 'Health zones' : `Level ${u.level}`}
                        path={u.url}
                      />
                    ))
                  ) : (
                    <Text size="sm" c="dimmed">No admin levels available for this country.</Text>
                  )}
                  {detail.languages.length > 0 && (
                    <Text size="xs" c="dimmed">
                      These CSVs include your {detail.languages.length} translation column
                      {detail.languages.length > 1 ? 's' : ''}.
                    </Text>
                  )}
                </Stack>
              </Stack>
            )}
          </Stack>
        )}
      </Stack>
    </Paper>
  );
}
