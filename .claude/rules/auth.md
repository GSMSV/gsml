# Auth Rules — OAuth, JWT, API Keys

Cross-cutting: spans `apps/api/app/{deps,security,routers/auth,routers/keys}.py` and
`apps/web/src/{lib/auth.ts,api/client.ts,pages/Callback.tsx}`.

## Two credentials, never mixed

| Credential | Issued by | Used for | Verified by |
|---|---|---|---|
| JWT (HS256, `JWT_EXPIRE_HOURS`, default 24h) | `POST /api/auth/callback` | Dashboard `/api/*` | `decode_jwt` → `get_current_user` |
| API key `sk-<48 base62>` (`API_KEY_EXPIRE_DAYS`, default 30d) | `POST /api/keys` | OpenAI clients on `/v1/*` | SHA-256 hash lookup → `get_api_user` |

Both arrive as `Authorization: Bearer <token>`. The `sk-` prefix is what distinguishes them.

## Choosing the dependency

Exactly three exist in `apps/api/app/deps.py`. Picking the wrong one is the main bug class in this area:

- `get_current_user` — **JWT only.** Dashboard routes (`/api/me`, `/api/keys`, `/api/usage`). Raises `HTTPException`.
- `get_api_user` — **API key only.** Billed inference (`POST /v1/chat/completions`). Raises `OpenAIError`.
- `get_user_any` — **either.** Only for `/v1` routes the dashboard also calls, currently `GET /v1/models`.
  Using `get_api_user` there broke the dashboard's model list (fixed in `620a232`).

A new `/v1` route that costs tokens uses `get_api_user`. A new read-only `/v1` route the web app needs uses
`get_user_any`. Never authenticate a `/api/*` route with an API key.

## Invariants

- **Only the hash is stored.** `key_hash` = SHA-256 hex, `key_prefix` = `plain[:9]` (`"sk-"` + 6 chars) for display.
  The plaintext exists once, in the `IssuedKeyResponse` of issue/rotate. Never log it, never persist it, never
  return it from any other endpoint.
- **One key per user** — `api_keys.user_id` is `unique`. Issue returns 409 if one exists; rotate deletes then
  recreates. Supporting multiple keys is a schema change, not a route change (see `apps/api/README.md` §5).
- **Rotate and delete invalidate immediately.** In-flight clients get 401 on the next request. Any UI for these
  must confirm first.
- **Expiry is checked at request time**, not by a job: `key.expires_at < utcnow-naive` → `expired_api_key()`.
  `expires_at` is stored naive UTC; compare with `datetime.now(timezone.utc).replace(tzinfo=None)`.
- `JWT_SECRET` has an insecure default (`"change-me"`). Never hardcode a real secret, commit one, or print
  `settings.JWT_SECRET`.

## DataGSM OAuth flow

1. `apps/web` renders `<OAuthLoginButton />` from `@themoment-team/datagsm-oauth-react`, configured by
   `OAuthProvider` in `main.tsx` (`authMode="STANDARD"`).
2. The provider redirects to `VITE_OAUTH_REDIRECT_URI` (`/auth/callback`) with `?code=`.
3. `Callback.tsx` POSTs the code to `/api/auth/callback` **once** — the `ran` ref guard is required because the
   code is single-use and StrictMode double-invokes effects.
4. The backend exchanges it server-side (`OAUTH_AUTH_BASE/v1/oauth/token`), fetches
   `OAUTH_RESOURCE_BASE/userinfo`, upserts the user, and returns a JWT.
5. `authStore.set(token)` → redirect to `/dashboard`.

Rules:

- The **client secret never reaches the browser.** `OAUTH_CLIENT_SECRET` is backend-only; only
  `VITE_OAUTH_CLIENT_ID` and `VITE_OAUTH_REDIRECT_URI` are exposed to the web build.
- `OAUTH_REDIRECT_URI` (backend) and `VITE_OAUTH_REDIRECT_URI` (web build arg) must be the same string, and must
  match what is registered with DataGSM. `docker-compose.yml` feeds both from `OAUTH_REDIRECT_URI`.
- The subject is resolved as `sub ?? id ?? email` and stored in `users.oauth_sub` (unique). Do not key users on
  email alone.
- **Profile is written on first login only.** Existing users are not updated from `userinfo`, so `usage_limit`
  and `max_concurrent` set by an admin survive re-login. Changing this to an update-on-every-login would silently
  reset operator overrides — don't, unless explicitly asked.
- New users get `DEFAULT_CREDIT_LIMIT` / `DEFAULT_MAX_CONCURRENT` from settings; there is no admin UI, so limits
  are adjusted with SQL against `data/gsml.db`. `usage_limit` is **credits**, not tokens.

## CORS

`CORS_ORIGINS` is a comma-separated list parsed into `settings.cors_origin_list`. `allow_credentials=False` —
auth rides in the header, not cookies; do not switch to cookie auth without revisiting this. Any header the
browser must read (e.g. the `X-RateLimit-*` quota headers) has to be listed in `expose_headers` in `main.py`.
