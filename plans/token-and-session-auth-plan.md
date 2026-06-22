# Plan: `/token` retrieval endpoint + cookie-session browser auth

## Goal

Two complementary additions to authentication:

1. **Let a logged-in user retrieve (and rotate) their API token** through a
   dedicated endpoint, so they can copy it into scripts / KoboToolbox / curl
   without going through the admin or re-POSTing credentials.
2. **Authenticate browser requests with a Django session cookie** established at
   login, instead of a token kept in `localStorage`. The cookie becomes the
   browser's auth; the token becomes a credential you *copy out* for non-browser
   use (exactly what the new endpoint is for).

These are additive — token-only API clients (curl, Kobo) keep working header-only
and are unaffected.

Decisions locked in with the user:

| Question | Decision |
|----------|----------|
| How the browser holds auth | **Cookie-only** — drop the `localStorage` token entirely; rely on the HttpOnly session cookie. Token fetched on-demand only for copying. |
| What `/token` returns | **Return current token + allow rotation** — `GET` returns it (`get_or_create`), `POST` regenerates (invalidates the old one). |
| Endpoint path | **`GET`/`POST /api/me/token`** — pairs naturally with the existing `/api/me`; reads as "the current user's token". |
| API docs | Endpoints **must appear in the drf-spectacular schema** (`/api/docs/`, `/api/redoc/`) with documented request/response shapes via `@extend_schema`. |

> Naming note: `POST /api/token` (DRF `ObtainAuthToken`) already exists and issues
> a token *from username/password*. The new `/api/me/token` returns/rotates the
> token for an *already-authenticated* user (cookie or token).

---

## Reference: what already exists

- **API auth**: DRF `TokenAuthentication` only, set globally at
  `config/settings.py:185-203`. Default permission is `AllowAny`; views opt into
  protection. Tokens are DRF `rest_framework.authtoken` — DB-backed, opaque,
  **one per user, no expiry**. Sent as `Authorization: Token <key>`.
- **Token issuance already exists**: `POST /api/token` → `config/urls.py:66` →
  `apps/accounts/views.py:16` (`ObtainAuthToken.as_view()`). `GET /api/me`
  (`views.py:23-31`, `IsAuthenticated`) returns user info; the SPA hits it on
  mount to validate its stored token.
- **Sessions already installed but not wired into DRF**: `SessionMiddleware`
  (`settings.py:109`) and `django.contrib.sessions` (`settings.py:82`) power the
  Django admin. Not currently in `DEFAULT_AUTHENTICATION_CLASSES`.
- **CSRF infra already configured**: `CSRF_TRUSTED_ORIGINS` (`settings.py:65-72`)
  and `SECURE_PROXY_SSL_HEADER` (`settings.py:76`) for the DO TLS-terminating
  proxy. `CsrfViewMiddleware` is active (`settings.py:111`).
- **Anonymous UI exemption**: `apps/geocoding/permissions.py` →
  `IsAuthenticatedOrUIClient` lets the SPA call `POST /geocode_single` and
  `POST /reverse_geocode` without a login, validated by a soft Origin/Referer
  check (added in commit `49139f3`). Explicitly documented as not a hard
  boundary; paired with throttling. **Stays as-is** — it serves anonymous public
  users, which is orthogonal to logged-in sessions.
- **Frontend auth**: `frontend/src/api/auth.ts` (token in `localStorage` key
  `geocoder_token`, `authHeaders()` builds the header), `client.ts:11-27` (merges
  `authHeaders()` into every request), `context/AuthContext.tsx:25` (confirms
  token via `/api/me` on mount). Login page `pages/LoginPage.tsx`, header toggle
  `pages/MainPage.tsx:70-79`, batch upload gated on `loggedIn`
  (`components/BatchUpload.tsx:62-71`).
- **Committed build**: the production SPA bundle is committed to `static/` and
  served same-origin by WhiteNoise. Frontend source changes don't ship until the
  bundle is rebuilt.
- **Tests**: `tests_django/test_auth.py` covers `/api/token`, `/api/me`, token
  gating, and the same-origin exemption — the template for new cases.

---

## Phase 1 — Backend: session auth + login/logout

1. **Enable session auth** at `config/settings.py:186`, *before* token auth:
   ```python
   "DEFAULT_AUTHENTICATION_CLASSES": [
       "rest_framework.authentication.SessionAuthentication",
       "rest_framework.authentication.TokenAuthentication",
   ],
   ```
   DRF only enforces CSRF when a **session** user is present, so token-only
   clients (no session cookie) are unaffected — curl/Kobo keep working.

2. **Add login/logout endpoints** in `apps/accounts/views.py`:
   - `POST /api/login` — validate `{username, password}` (reuse DRF's
     `AuthTokenSerializer` for credential checking, or
     `django.contrib.auth.authenticate`), then `django.contrib.auth.login(request, user)`
     to set the `sessionid` cookie. Return the same shape as `/api/me`.
   - `POST /api/logout` — `django.contrib.auth.logout(request)` (flushes the
     session). `IsAuthenticated`.

3. **Plant the CSRF cookie**: decorate `me` (`apps/accounts/views.py:23`) with
   `@ensure_csrf_cookie` so the GET the SPA makes on mount sets the `csrftoken`
   cookie. Session-authed POSTs then succeed once the SPA echoes it as
   `X-CSRFToken`. Anonymous UI geocode calls remain CSRF-free (no session → no
   enforcement), so the public no-login flow is untouched.

4. **Cookie hardening** in `config/settings.py` (near the CSRF block,
   `settings.py:65-76`):
   ```python
   SESSION_COOKIE_SECURE = not DEBUG
   CSRF_COOKIE_SECURE = not DEBUG
   SESSION_COOKIE_SAMESITE = "Lax"   # default; fine for same-origin SPA
   CSRF_COOKIE_HTTPONLY = False      # SPA JS must read it to echo X-CSRFToken
   ```
   The session cookie stays HttpOnly (Django default) → not stealable via XSS, a
   security improvement over the `localStorage` token.

## Phase 2 — Backend: `/api/me/token` (retrieve + rotate)

In `apps/accounts/views.py`, add a view (`IsAuthenticated`; works via cookie or
token auth) registered at `config/urls.py` next to `api/me`:

- `GET /api/me/token` → `Token.objects.get_or_create(user=request.user)` →
  `{"token": key}`.
- `POST /api/me/token` → rotate: delete the existing token and create a new one
  inside a transaction → `{"token": key}`. Invalidates any old copies.

No SPA catch-all regex change needed — the route is under the already-excluded
`api/` prefix (`config/urls.py:84`).

**API docs (required):** decorate every new view (`login`, `logout`, and the
`me/token` GET/POST) with `@extend_schema` so they render in the drf-spectacular
schema at `/api/docs/` and `/api/redoc/` — matching the existing `me` view
(`apps/accounts/views.py:19-20`). Specify:
- `request` / `responses` shapes (the `{token}` response; `{username,password}`
  login request; the user-info response shared with `/api/me`).
- A clear `description` and, since GET vs POST on `me/token` differ, distinct
  `summary` per method (use `@extend_schema_view` or per-method decorators so
  Swagger shows "retrieve token" vs "rotate token" separately).
- Confirm after wiring: `GET /api/schema/` lists `/api/me/token`, `/api/login`,
  `/api/logout`, and they render in `/api/docs/`. Add a smoke assertion in the
  test phase that the schema contains the new paths.

## Phase 3 — Frontend: cookie-only auth

1. **`frontend/src/api/auth.ts`** — remove `localStorage` entirely
   (`getToken`/`setToken`/`clearToken`/`authHeaders` go away):
   - `login()` → `POST /api/login` with `credentials: 'include'`.
   - `logout()` → `POST /api/logout` with `credentials: 'include'`.
   - Add `getApiToken()` (`GET /api/me/token`) and `rotateApiToken()`
     (`POST /api/me/token`).
   - Add a `getCsrfToken()` helper reading the `csrftoken` cookie.
2. **`frontend/src/api/client.ts`** — every request gets `credentials: 'include'`
   and, on unsafe methods, an `X-CSRFToken` header from the cookie. Drop the
   `authHeaders()` merge.
3. **`frontend/src/context/AuthContext.tsx`** — confirm the session via
   `GET /api/me` with `credentials: 'include'` (no token header); this is also
   what plants the CSRF cookie.
4. **New UI** for logged-in users (e.g. on `MainPage`): a "Show / copy API token"
   action calling `getApiToken()`, plus a "Regenerate" action calling
   `rotateApiToken()` (with a confirm — it invalidates existing copies).
5. **Rebuild the committed `static/` bundle** — frontend changes don't ship
   otherwise.

## Phase 4 — Tests

Extend `tests_django/test_auth.py`:

- Session login (`POST /api/login`) sets `sessionid`; subsequent protected POST
  (e.g. `/geocode` batch) succeeds with the session cookie + CSRF token.
- Protected session POST **without** the CSRF token is rejected (403).
- Token-only client (header, no session) still works and is **not** subject to
  CSRF — regression guard for curl/Kobo.
- `GET /api/me/token` returns a token via both cookie auth and token auth.
- `POST /api/me/token` rotates: old token no longer authenticates, new one does.
- `POST /api/logout` flushes the session; subsequent protected call is denied.
- Anonymous UI geocode (`IsAuthenticatedOrUIClient`) still works unchanged.
- `GET /api/schema/` (200) includes the `/api/me/token`, `/api/login`, and
  `/api/logout` paths — guards that the docs stay in sync.

---

## Migration / rollout note

After deploy, existing users with a `localStorage` token appear logged-out
(browser auth is cookie-only now) and must log in once to get a session.
Acceptable for this app's size. Their underlying API token is unchanged and still
valid for header use.

## Effort / risk

- Backend ≈ half a day; infra (sessions, CSRF config) already exists.
- Frontend ≈ half a day plus the `static/` rebuild.
- **Main risk: CSRF wiring** (cookie plant on `/api/me` + `X-CSRFToken` echo on
  unsafe methods). It's the one place that bites if rushed — Phase 4 tests cover
  it explicitly.
