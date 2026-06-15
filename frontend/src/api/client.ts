import type {
  AvailableLevels,
  BatchResult,
  BoundaryCsvProject,
  Country,
  PcodeResult,
  SecondaryTypes,
} from './types';
import { authHeaders } from './auth';

async function request<T>(input: RequestInfo, init?: RequestInit): Promise<T> {
  const res = await fetch(input, {
    ...init,
    headers: { ...authHeaders(), ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const message =
      (body as { error?: string; detail?: string }).error ??
      (body as { detail?: string }).detail ??
      `HTTP ${res.status}`;
    throw new Error(message);
  }
  // 204 No Content has no body to parse.
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export function fetchCountries(): Promise<Country[]> {
  return request<Country[]>('/countries');
}

export function fetchAvailableLevels(iso2: string): Promise<AvailableLevels> {
  return request<AvailableLevels>(`/api/available_levels?country=${iso2}`);
}

export function fetchSecondaryTypes(iso2: string): Promise<SecondaryTypes> {
  return request<SecondaryTypes>(`/api/secondary_types?country=${iso2}`);
}

export function geocodeSingle(address: string, country?: string): Promise<PcodeResult> {
  return request<PcodeResult>('/geocode_single', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(country ? { address, country } : { address }),
  });
}

export function reverseGeocode(lat: number, lon: number, country?: string): Promise<PcodeResult> {
  return request<PcodeResult>('/reverse_geocode', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(country ? { latitude: lat, longitude: lon, country } : { latitude: lat, longitude: lon }),
  });
}

export function geocodeBatch(form: FormData): Promise<BatchResult> {
  return request<BatchResult>('/geocode', { method: 'POST', body: form });
}

// --- Boundary CSV lists ---

interface Paginated<T> {
  results: T[];
}

const JSON_HEADERS = { 'Content-Type': 'application/json' };

export async function fetchBoundaryProjects(): Promise<BoundaryCsvProject[]> {
  const data = await request<Paginated<BoundaryCsvProject> | BoundaryCsvProject[]>(
    '/api/boundary-projects/'
  );
  return Array.isArray(data) ? data : data.results;
}

export function fetchBoundaryProject(slug: string, country?: string): Promise<BoundaryCsvProject> {
  const qs = country ? `?country=${encodeURIComponent(country)}` : '';
  return request<BoundaryCsvProject>(`/api/boundary-projects/${slug}/${qs}`);
}

export function createBoundaryProject(name: string, slug: string): Promise<BoundaryCsvProject> {
  return request<BoundaryCsvProject>('/api/boundary-projects/', {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify({ name, slug }),
  });
}

export function deleteBoundaryProject(slug: string): Promise<void> {
  return request<void>(`/api/boundary-projects/${slug}/`, { method: 'DELETE' });
}

export function updateBoundaryProject(
  slug: string,
  patch: Partial<Pick<BoundaryCsvProject, 'name' | 'label_column_name'>>
): Promise<BoundaryCsvProject> {
  return request<BoundaryCsvProject>(`/api/boundary-projects/${slug}/`, {
    method: 'PATCH',
    headers: JSON_HEADERS,
    body: JSON.stringify(patch),
  });
}

export function addBoundaryLanguage(slug: string, header: string): Promise<unknown> {
  return request<unknown>(`/api/boundary-projects/${slug}/languages/`, {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify({ header }),
  });
}

export function deleteBoundaryLanguage(slug: string, languageId: number): Promise<void> {
  return request<void>(`/api/boundary-projects/${slug}/languages/${languageId}/`, {
    method: 'DELETE',
  });
}
