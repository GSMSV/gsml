# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

The project name is "gsml".

OpenAI-compatible LLM proxy with a React dashboard. Monorepo with two apps:
- `apps/api/` — FastAPI backend (Python 3.12+)
- `apps/web/` — React + TypeScript frontend (Vite)

## Setup

1. Copy `.env.example` → `.env` and fill in OAuth credentials and a long random `JWT_SECRET`.
2. Copy `upstream.example.yml` → `upstream.yml` and point it at your external llama-server host. This file is **not** managed by docker-compose.
3. `docker compose up --build` starts the API (port 8000) and web (port 5173).

For backend-only local dev: `cd apps/api && pip install -e . && uvicorn app.main:app --reload`

## Upstream Config

`upstream.yml` controls live LLM routing with sticky balancing by `conv_id`. Edits affect in-flight requests. Validate YAML structure before writing changes; do not add instance entries without confirming the host is reachable.

## Inference Transport

`/v1/chat/completions` requests are passed through (thinly) to the upstream llama-server's OpenAI-compatible `/v1/chat/completions` endpoint (`apps/api/app/upstream/openai_passthrough.py`). `tools` / `tool_choice` / `response_format` are forwarded unchanged; the proxy injects `id_slot` (slot pinning for KV-cache reuse), `cache_prompt`, `n=1`, and `stream_options.include_usage`.

**Deployment requirement:** llama-server must be launched with `--jinja` and a tool-capable chat template (Qwen / Hermes, `<tool_call>`) or tool calling silently degrades to plain text. Slot pinning assumes the build honors `id_slot` on the OAI endpoint — if a build does not, set `UPSTREAM_SLOT_PINNING=false` and rely on `cache_prompt` prefix-match.

## Branch Workflow

Work on feature branches; open a PR to merge into `master`. Do not push directly to `master`.

## Commits

Use the `/commit` skill for all commits. Korean descriptions, format `type : 설명` (space on both sides of colon).

**Never add AI co-author lines** (`Co-Authored-By` footers are prohibited in this repo).
