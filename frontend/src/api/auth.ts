// Token storage + helpers for DRF token authentication.
// The token is kept in localStorage so it survives reloads; it is sent as an
// `Authorization: Token <token>` header on API requests (see client.ts).

const TOKEN_KEY = 'geocoder_token';

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

export function authHeaders(): Record<string, string> {
  const token = getToken();
  return token ? { Authorization: `Token ${token}` } : {};
}

// Exchange username/password for an API token. Throws on bad credentials.
export async function login(username: string, password: string): Promise<void> {
  const res = await fetch('/api/token', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) {
    throw new Error('Invalid username or password');
  }
  const data = (await res.json()) as { token: string };
  setToken(data.token);
}

export function logout(): void {
  clearToken();
}
