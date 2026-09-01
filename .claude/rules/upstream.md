# Upstream Rules — Routing, Slots, Streaming, Quota

Covers `apps/api/app/upstream/*` and `apps/api/app/routers/openai_proxy.py`.

## Request path

`POST /v1/chat/completions`
→ `get_api_user` (API key)
→ pre-flight quota check
→ `_conv_id(user_id, X-Conversation-ID)`
→ `Balancer.acquire(conv_id)` → `(InstanceNode, slot_id)`
→ per-user concurrency slot
→ `build_native_request` → llama-server **native `/completion`** (not `/v1/chat/completions`)
→ response converted back to OpenAI shape
→ `_log_and_charge` + `write_conversation_log`
→ release concurrency slot **and** balancer entry.

Everything inference-related goes through the native path; `cache_prompt: true` + a pinned `slot_id` is what
preserves the KV cache across turns. `GET /v1/models` is the one plain proxy pass-through.

## `upstream.yml`

- **Not in git** (`.gitignore`), not managed by docker-compose beyond a read-only bind mount. Copy from
  `upstream.example.yml`.
- Resolved by `UPSTREAM_YML` env var, else by walking parents from `app/upstream/__init__.py`. Missing file →
  `RuntimeError` at startup; the app will not boot.
- `slot_count` **must equal that llama-server's `--parallel`**. Too high and the balancer hands out slot ids the
  server does not have; too low and capacity is wasted.
- `url` must have no trailing slash (the loader strips one defensively).
- Edits affect live routing. Validate the YAML and confirm the host is reachable before adding an instance —
  a dead entry starts `ALIVE` and takes `fail_threshold` health checks (default 2 × 30s) to be evicted, sending
  real traffic to a black hole in the meantime.

## Balancer invariants

`Balancer` (`upstream/balancer.py`) owns `conv_id → (node, slot)`; `InstanceSlotManager`
(`upstream/instance_node.py`) owns `conv_id → slot_id` LRU within one node.

- **`acquire()` and `release()` must pair on every path, including errors.** `acquire` increments an in-flight
  counter; a missed `release` pins the conv forever and leaks a slot. In `openai_proxy.py` the non-stream path
  releases in `finally`, the stream path releases inside the generator's `finally` *and* in the
  `except BaseException` guard around generator setup. Preserve both when editing.
- **`conv_id` is user-scoped**: `f"{user_id}:{X-Conversation-ID or 'default'}"`. Never route on a raw
  client-supplied header — two users sending the same id would share a KV cache.
- Placement is least-slots-used across `ALIVE` nodes; an existing conv is sticky to its node while that node lives.
- Eviction order when a node is full: global idle-conv LRU first, then forced in-node LRU (logged as a warning —
  it means all slots are mid-request).
- Health check hits `GET /health`; **200 and 503 both count as alive** — 503 just means no free slot (`8dc4679`).
  Any exception counts as failure; `fail_threshold` consecutive failures → `DEAD` → all convs on that node are
  evicted and re-placed elsewhere, losing their KV cache.
- No alive node → `RuntimeError` from the balancer, converted to `service_unavailable()` (503) at the call site.
  Do not let a bare `RuntimeError` escape to the client.
- The balancer is an in-process singleton created in `main.py`'s lifespan. Reach it with `get_balancer()`;
  never construct a second `Balancer`, and never call `init_balancer()` outside lifespan.

## Streaming

- Streaming and non-streaming take **different concurrency paths**: non-stream uses the
  `async with acquire_slot(...)` context manager; streaming calls `try_acquire` before returning the
  `StreamingResponse` and releases in the generator, because the response outlives the handler. Do not
  "simplify" the streaming path into the context manager — it would release the slot before the stream ends.
- `stream_options.include_usage` is forced on for streaming requests.
- Token accounting happens in the generator's `finally`, so a client disconnect still bills.
  `asyncio.CancelledError` and `httpx.HTTPError` are swallowed there deliberately.
- llama-server field names vary by version: read `tokens_evaluated`/`prompt_tokens` and
  `tokens_predicted`/`predicted_n` with the existing `or` fallbacks. If usage is missing, fall back to
  `token_count.count_messages` (tiktoken `cl100k_base`, approximate for non-OpenAI models).
- The SSE terminator is a usage-bearing chunk followed by `data: [DONE]`. Keep that contract — OpenAI SDKs rely on it.
- `messages_to_chatml` hardcodes ChatML and leaves the assistant turn open so the model continues from it.
  `LLAMA_CHAT_TEMPLATE` exists in settings but is not wired in; a model needing another template requires a real
  change here, not a config tweak.

## Quota and rate limiting

- **Quota is checked before the request and charged after it.** A single request can overshoot `usage_limit`;
  that is accepted. The pre-flight check is `current_usage >= usage_limit` → `insufficient_quota()` (429).
- Per-user concurrency (`max_concurrent`) is enforced by `app/concurrency.py`, an in-process dict — correct only
  for a single uvicorn worker on a single event loop. Exceeding it → `rate_limited()` (429).
- `X-RateLimit-Limit-Tokens` / `X-RateLimit-Remaining-Tokens` are set on `/v1` responses and must stay in
  `expose_headers` in `main.py` for the browser to read them.
- Usage resets at local midnight (`APP_TIMEZONE`) via APScheduler, with `catch_up_resets()` on boot covering
  downtime. `RequestLog` rows older than `REQUEST_LOG_RETENTION_DAYS` are purged at 00:05 local.
- Every completed request writes a `RequestLog` row (with `source`: `"api"` or `"web"`) **and** a full-content
  JSONL line under `CONVERSATION_LOG_DIR`. The JSONL retention job does not exist — only `RequestLog` is purged.
