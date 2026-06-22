// Cookie-based session auth for the web UI.
//
// Logging in opens a Django session (HttpOnly `sessionid` cookie); the browser
// then sends it automatically on every same-origin request (see client.ts,
// which sets `credentials: 'include'`). No token is kept in JS storage.
//
// The API token still exists for headless/scripted access — fetch it on demand
// via getApiToken() so the user can copy it; rotateApiToken() issues a new one.

// Read a cookie value by name (used for the CSRF token).
export function getCookie(name: string): string | null {
  const match = document.cookie.match(new RegExp('(?:^|; )' + name + '=([^;]*)'));
  return match ? decodeURIComponent(match[1]) : null;
}

// Django's default CSRF cookie/header names.
const CSRF_COOKIE = 'csrftoken';
const CSRF_HEADER = 'X-CSRFToken';

// Headers required for an unsafe (POST/PUT/PATCH/DELETE) session request.
export function csrfHeaders(): Record<string, string> {
  const token = getCookie(CSRF_COOKIE);
  return token ? { [CSRF_HEADER]: token } : {};
}

// Log in and start a session. Throws on bad credentials.
export async function login(username: string, password: string): Promise<void> {
  const res = await fetch('/api/login', {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...csrfHeaders() },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) {
    throw new Error('Invalid username or password');
  }
}

// End the session.
export async function logout(): Promise<void> {
  await fetch('/api/logout', {
    method: 'POST',
    credentials: 'include',
    headers: csrfHeaders(),
  });
}

// Return the current user's API token for headless access.
export async function getApiToken(): Promise<string> {
  const res = await fetch('/api/me/token', { credentials: 'include' });
  if (!res.ok) throw new Error('Could not fetch API token');
  const data = (await res.json()) as { token: string };
  return data.token;
}

// Issue a fresh API token, invalidating the previous one.
export async function rotateApiToken(): Promise<string> {
  const res = await fetch('/api/me/token', {
    method: 'POST',
    credentials: 'include',
    headers: csrfHeaders(),
  });
  if (!res.ok) throw new Error('Could not regenerate API token');
  const data = (await res.json()) as { token: string };
  return data.token;
}
