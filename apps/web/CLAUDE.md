# apps/web — React Dashboard

Rules for the Vite + React + TypeScript SPA. Read together with `.claude/rules/auth.md`
when touching login, the callback, or API keys.

## Layout

| Path | Role |
|---|---|
| `src/main.tsx` | Providers: `QueryClientProvider` → `OAuthProvider` → `BrowserRouter` |
| `src/App.tsx` | Routes + the `Protected` wrapper |
| `src/api/client.ts` | Axios instance, auth interceptors, **all shared response types** |
| `src/lib/auth.ts` | `authStore` — the only module that touches `localStorage` |
| `src/pages/` | `Login`, `Callback`, `Dashboard` |
| `src/components/` | `KeyCard`, `UsageCard` |
| `src/styles.css` | The entire stylesheet — global classes, no CSS modules, no framework |

## Conventions

- Function components with `export default`; named exports only for helpers used elsewhere.
- Double-quoted strings, semicolons, 2-space indent. No Prettier/ESLint config exists — match surrounding code.
- Server state is **TanStack Query only**; there is no Redux/Zustand/Context store. Keys in use:
  `["me"]`, `["key"]`, `["usage-today"]`, `["usage-history"]`. Invalidate with
  `qc.invalidateQueries({ queryKey: [...] })` after a mutation instead of refetching manually.
- Query functions unwrap axios themselves: `queryFn: async () => (await api.get("/api/me")).data`.
- Response shapes are declared as `type` aliases at the bottom of `src/api/client.ts` — put new ones there,
  not next to the component, and keep them in sync with `apps/api/app/schemas.py`.
- Styling is class-based from `styles.css` (`container`, `card`, `row`, `spaced`, `muted`, `mono`, `warn`,
  `modal-bg`, `modal`, `bar`, `spark`; buttons via `secondary` / `danger`). Inline `style` is acceptable only
  for one-off spacing/sizing, as existing code does. Add a class for anything reused.
- All user-facing text is **Korean**; code, comments, and types are English.

## Hard rules

- **`npm run build` does not type-check** — it is bare `vite build` with no `tsc -b`. `tsconfig.json` is
  `strict` with `noUnusedLocals`/`noUnusedParameters`, so type errors ship silently. After changing any
  `.ts`/`.tsx`, run `cd apps/web && npx tsc --noEmit`.
- **There are no tests.** Do not add a test runner unless asked; verify with `npm run dev` against a local API.
- **`VITE_*` variables are baked in at build time**, passed as Docker build `ARG`s in `apps/web/Dockerfile`
  and `docker-compose.yml`. Changing `VITE_API_BASE_URL`, `VITE_OAUTH_CLIENT_ID`, or `VITE_OAUTH_REDIRECT_URI`
  requires `docker compose build web`, not a restart. Never read them outside module scope expecting runtime values.
- **Read and write the JWT only through `authStore`.** No other module should call `localStorage` directly.
- The 401 interceptor in `src/api/client.ts` deliberately **exempts `/v1/*`**: those routes authenticate with a
  `sk-` API key, so a 401 there says nothing about the dashboard session. Clearing the token on a `/v1` 401 logged
  users out spuriously (fixed in `620a232`) — preserve that exemption when editing the interceptor.
- Routing is client-side with an nginx `try_files ... /index.html` fallback (`nginx.conf`). A new route needs no
  server change, but must be reachable from `App.tsx`; unknown paths redirect to `/`.
- `react-markdown`, `react-syntax-highlighter`, and `uuid` are leftovers from the removed web-chat feature
  (`38fe8c8`) and are unused. Don't build on them assuming a chat UI exists; if a task makes them dead weight
  for good, removing them from `package.json` is fair game.

## Dashboard behaviour worth preserving

- `Callback.tsx` guards the effect with a `ran` ref because React StrictMode double-invokes effects in dev and
  the OAuth `code` is single-use — the second exchange fails. Keep the guard.
- `KeyCard` shows a freshly issued key exactly once, in a modal, with a clipboard fallback for non-secure
  contexts. Do not persist `IssuedKey.api_key` in state that outlives the modal, in `localStorage`, or in a query cache.
- Destructive key actions confirm first: rotate uses an in-app modal, delete uses `confirm()`. Keep a confirmation
  step on any new destructive action.
