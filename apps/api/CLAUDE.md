# apps/api — FastAPI Backend

Rules for the Python backend. Read together with `.claude/rules/auth.md` and
`.claude/rules/upstream.md` when touching auth or the `/v1` proxy.

## Layout

| Path | Role |
|---|---|
| `app/main.py` | App factory, lifespan (`init_db` → `catch_up_resets` → scheduler → balancer), exception handlers, router registration |
| `app/config.py` | `Settings` (pydantic-settings). Every tunable lives here |
| `app/db.py` | Engine, `SessionLocal`, `Base`, `get_db` |
| `app/models.py` | `User` / `ApiKey` / `RequestLog` |
| `app/schemas.py` | Pydantic request/response models |
| `app/deps.py` | The three auth dependencies |
| `app/errors.py` | OpenAI-format error factories |
| `app/pricing.py` | Token usage → credits. The only place a rate is applied |
| `app/routers/` | `auth`, `me`, `keys`, `usage` (dashboard) + `openai_proxy` (`/v1`) |
| `app/upstream/` | `upstream.yml` parsing, `Balancer`, `InstanceNode`, llama native adapter |
| `app/slot_manager.py` | **Deprecated.** Superseded by `upstream/instance_node.py`. Do not import or extend it |

## Conventions

- Python 3.12+. Modern typing only: `X | None`, `list[str]`, `dict[str, int]` — never `Optional`/`List`.
- SQLAlchemy 2.0 style: `Mapped[...]` + `mapped_column(...)` on `DeclarativeBase`. No legacy `Column()`.
- Relative imports inside `app` (`from ..config import settings`).
- Comments and docstrings are **Korean**; identifiers and log messages are English.
- Logging: `logger = logging.getLogger(__name__)` at module top, `%s` lazy formatting, never f-strings in log calls.
- Routers: `APIRouter(prefix="/api/<name>", tags=["<name>"])`, one router per file, registered in `main.py`.
- Handlers declare a return type and (for non-trivial bodies) `response_model=`.
- New config values go in `Settings` **and** `.env.example`, with a default that lets the app boot.

## Hard rules

- **No test suite and no linter exist.** Do not add pytest/ruff/mypy config unless asked. Verify changes by
  `cd apps/api && python -c "import app.main"` plus a manual `uvicorn app.main:app --reload` run.
- **There are no migrations.** `init_db()` calls `create_all()`, which only creates *missing tables* — it will
  not add a column to an existing table. Adding a column to `User`/`ApiKey`/`RequestLog` requires an explicit
  `ALTER TABLE` in `init_db()` — add it to `_ADD_COLUMN_STATEMENTS`, which tries each one and ignores the
  failure when the column already exists — otherwise existing `data/gsml.db` deployments break at query time.
  A one-shot data fix (e.g. converting existing values to a new unit, as opposed to just adding a column) is
  **not** automated here — it is run by hand as a one-off `UPDATE` against `data/gsml.db` at deploy time,
  not from app code, so a restart can't reapply it.
- **`db.commit()` is the caller's job.** Routers commit; helpers do not. After creating a row that the response
  needs, `db.refresh(record)`.
- **`app/concurrency.py` is process-local.** It assumes one uvicorn worker on one event loop, so counters need
  no lock. Do not add workers, `--workers`, or threads without replacing it (see `README.md` §3).
- Never log, return, or persist a plaintext API key or JWT. Only `key_hash` (SHA-256) and `key_prefix` are stored.
- `app/conversation_logger.py` writes full prompts and completions to JSONL under `CONVERSATION_LOG_DIR`.
  Treat that directory as personal data: never print its contents into a PR, an issue, or a chat.

## Time handling

Two clocks coexist — mixing them is a real bug source.

- **Storage / logs are naive UTC.** Model defaults use `_utcnow()`; comparisons against DB columns must strip
  tzinfo, as `deps.py` does with `datetime.now(timezone.utc).replace(tzinfo=None)`.
- **User-facing boundaries are local (`APP_TIMEZONE`, default Asia/Seoul)**, via `app/timezone_util.py`.
  Quota reset, `catch_up_resets`, log purge, and `reset_at` in the usage response all use `today_local()` /
  `next_midnight_local()` — never `datetime.utcnow().date()`.

Use `timezone_util` helpers rather than reaching for `ZoneInfo` again.

## Errors

Pick by route family — the two are not interchangeable:

- `/api/*` (dashboard, JWT): raise `HTTPException(status_code=..., detail=...)`.
- `/v1/*` (OpenAI-compatible): raise the factories in `app/errors.py`
  (`invalid_api_key`, `expired_api_key`, `insufficient_quota`, `rate_limited`, `upstream_error`,
  `service_unavailable`). A raw `HTTPException` on `/v1` produces `{"detail": ...}`, which breaks OpenAI SDK
  clients that expect `{"error": {"message", "type", "code"}}`.

New `/v1` failure modes get a new factory in `errors.py` rather than an inline `OpenAIError(...)`.

## Stale docs

`apps/api/README.md` predates the balancer rewrite: `UPSTREAM_BASE_URL`, `DEFAULT_UPSTREAM`,
`UPSTREAMS` dict, and "유저별 asyncio.Semaphore" no longer exist. `.env.example` still lists
`UPSTREAM_BASE_URL`, which `Settings` ignores (`extra="ignore"`). Trust the code; if you touch these
areas, fix the doc in the same change.
