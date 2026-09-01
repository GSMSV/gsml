# Upstream Rules — Routing, Slots, Streaming, Quota

Covers `apps/api/app/upstream/*` and `apps/api/app/routers/openai_proxy.py`.

## Request path

`POST /v1/chat/completions`
→ `get_api_user` (API key)
→ pre-flight quota check
→ `_conv_id(user_id, X-Conversation-ID)`
→ `Balancer.acquire(conv_id)` → `(InstanceNode, slot_id)`
→ per-user concurrency slot
→ `apply_routing` (adds `id_slot` + `cache_prompt`) → llama-server **`/v1/chat/completions`**
→ response body forwarded unchanged
→ `_log_and_charge` + `write_conversation_log`
→ release concurrency slot **and** balancer entry.

The upstream's OpenAI-compatible endpoint does the work the proxy used to do by hand: it renders the model's own
Jinja chat template, parses `<think>` into `reasoning_content` and tool markup into `tool_calls`, and enforces a
grammar when `tools` is present. The proxy adds routing parameters and reads `usage` for billing; it does not
rewrite the response. `GET /v1/models` is likewise a plain pass-through.

## `upstream.yml`

- **Not in git** (`.gitignore`), not managed by docker-compose beyond a read-only bind mount. Copy from
  `upstream.example.yml`.
- Resolved by `UPSTREAM_YML` env var, else by walking parents from `app/upstream/__init__.py`. Missing file →
  `RuntimeError` at startup; the app will not boot.
- `slot_count` **must equal that llama-server's `--parallel`**. Too high and the balancer hands out slot ids the
  server does not have (llama.cpp wraps them with `id_slot % n_slots`, silently colliding two convs on one slot);
  too low and capacity is wasted.
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
- `stream_options.include_usage` is forced on for streaming requests; the usage-bearing chunk is where
  `_do_chat_stream` reads token counts.
- SSE lines are forwarded verbatim. The generator parses each `data:` payload only to accumulate `content`,
  `reasoning_content` and `tool_calls` deltas for the JSONL log and to read `usage` — it never re-emits a
  rewritten chunk. A non-200 from the upstream becomes one OpenAI-format error event followed by `[DONE]`.
- Token accounting happens in the generator's `finally`, so a client disconnect still bills.
  `asyncio.CancelledError` and `httpx.HTTPError` are swallowed there deliberately.
- Usage arrives in OpenAI shape (`prompt_tokens` / `completion_tokens`). If it is missing, fall back to
  `token_count.count_messages` (tiktoken `cl100k_base`, approximate for non-OpenAI models).
- The SSE terminator is a usage-bearing chunk followed by `data: [DONE]`, produced by the upstream. Keep the
  pass-through intact — OpenAI SDKs rely on that contract.
- **`id_slot` is the slot-pinning parameter name**, not `slot_id` — the latter is a pre-2024 llama.cpp name that
  no longer exists in the source, so sending it is silently ignored and the server picks a slot by prompt-LCP
  similarity instead (`-sps`, default 0.10). `apply_routing` sends `id_slot` + `cache_prompt` on every request;
  llama.cpp's oaicompat parser forwards unknown keys to the completion backend, which is why they work on the
  OpenAI endpoint. Both names are also stripped from client bodies via `_SERVER_CONTROLLED` — a client that
  could pick its own slot could evict another user's conversation.
- **The request body is forwarded as-is apart from `_SERVER_CONTROLLED`.** llama.cpp silently ignores fields it
  does not know (`functions`/`function_call`, `model`, `prediction`, `store`, `metadata`, `service_tier`, ...),
  so there is nothing to strip for those — note that the deprecated `functions`/`function_call` shape means tool
  calling fails with no error. Its own sampler extensions (`grammar`, `samplers`, `mirostat*`, `dry_*`, `xtc_*`,
  `top_k`, `min_p`, `repeat_penalty`, ...) are deliberately left reachable by clients.
- **Fields that do take effect and are still open**: `n` (aliased to `n_cmpl` — multiplies token cost),
  `max_tokens`/`max_completion_tokens` (no ceiling), `lora`, `ignore_eos`, `n_keep`, `n_cache_reuse`,
  `n_discard`. Quota is charged after the fact, so one request can overshoot `usage_limit` by a lot. Left open
  on purpose; revisit here before assuming a per-request cap exists.
- **The proxy does not touch the response.** `reasoning_content` and `tool_calls` come from llama-server's own
  parser, so nothing here needs updating when a new model family ships new markup. Run llama-server with
  `--jinja`, or `tools` is ignored and the model never sees the tool definitions.
- `LLAMA_CHAT_TEMPLATE` in settings is unwired and redundant — the template comes from the model. Override it on
  the llama-server side (`--chat-template` / `--chat-template-file`), not here.

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
  JSONL line under `CONVERSATION_LOG_DIR` (with `reasoning` and `tool_calls` keys when the upstream returned
  them). The JSONL retention job does not exist — only `RequestLog` is purged.
