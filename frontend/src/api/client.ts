import type { AvailableLevels, BatchResult, Country, PcodeResult, SecondaryTypes } from './types';
import { authHeaders } from './auth';

async function request<T>(input: RequestInfo, init?: RequestInit): Promise<T> {
  const res = await fetch(input, {
    ...init,
    headers: { ...authHeaders(), ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error((body as { error?: string }).error ?? `HTTP ${res.status}`);
  }
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
