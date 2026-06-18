"""llama-server OpenAI 호환 /v1/chat/completions 패스스루 클라이언트.

클라이언트의 OpenAI body를 (거의) 그대로 업스트림으로 전달한다. tools /
tool_choice / response_format은 무변형 통과시키고, llama-server가 `--jinja`
템플릿으로 도구 렌더링·grammar 제약·tool_call 파싱·스트리밍 델타를 모두 처리한다.

slot 고정(KV 캐시 재사용)을 위해 id_slot을 주입한다 — OAI 엔드포인트의 id_slot
패스스루가 배포 빌드에서 동작함을 확인(Plan A). 빌드 차이에 대비해
``UPSTREAM_SLOT_PINNING`` 설정으로 주입을 끌 수 있다.
"""
import json

import httpx

from ..config import settings
from ..conversation_logger import write_upstream_raw_log
from .client import make_client


# ---------------------------------------------------------------------------
# body 준비
# ---------------------------------------------------------------------------


def prepare_upstream_body(body: dict, slot_id: int) -> dict:
    """클라이언트 OpenAI body를 업스트림 요청 body로 준비한다.

    원본을 변형하지 않도록 얕은 복사 후 서버 제어 필드를 주입한다:
    - ``id_slot``: Balancer가 고정한 슬롯 (KV 캐시 재사용). ``UPSTREAM_SLOT_PINNING``
      이 꺼져 있으면 생략하고 ``cache_prompt`` prefix-match에 맡긴다.
    - ``cache_prompt``: prefix 캐시 활성.
    - ``n``: 단일 choice 강제 (로깅·과금이 단일 choice를 가정).
    - ``stream_options.include_usage``: 스트리밍 마지막 usage 청크 수신.

    ``tools`` / ``tool_choice`` / ``response_format`` 등 나머지는 그대로 통과한다.
    """
    out = dict(body)
    if settings.UPSTREAM_SLOT_PINNING:
        out["id_slot"] = slot_id
    out["cache_prompt"] = True
    out["n"] = 1
    if out.get("stream"):
        opts = dict(out.get("stream_options") or {})
        opts["include_usage"] = True
        out["stream_options"] = opts
    return out


# ---------------------------------------------------------------------------
# raw 로깅 / 에러 매핑
# ---------------------------------------------------------------------------


def _raw_log_base(body: dict, slot_id: int, base_url: str, direction: str) -> dict:
    """raw 업스트림 로그의 공통 필드. tools가 실제 요청 body에 포함되어
    업스트림으로 전달되므로 별도 client_tools 필드는 두지 않는다."""
    return {
        "direction": direction,
        "base_url": base_url,
        "slot_id": slot_id,
        "model": body.get("model", ""),
        "user_id": body.get("user", ""),
    }


def _map_upstream_error(status_code: int, data) -> Exception:
    """업스트림 비-2xx 응답을 OpenAI 에러로 매핑한다.

    4xx(잘못된 tools 스키마 등)는 상태코드를 보존해 그대로 전파하고,
    5xx는 502 upstream_error로 격하한다.
    """
    from ..errors import OpenAIError, upstream_error

    msg = ""
    if isinstance(data, dict):
        err = data.get("error")
        if isinstance(err, dict):
            msg = err.get("message", "")
        elif isinstance(err, str):
            msg = err
        msg = msg or data.get("message", "") or data.get("_raw_text", "")
    if 400 <= status_code < 500:
        return OpenAIError(
            status_code,
            msg or "Upstream rejected the request.",
            "invalid_request_error",
            "upstream_invalid_request",
        )
    return upstream_error(
        f"Upstream error ({status_code}): {msg}" if msg else f"Upstream error ({status_code})."
    )


# ---------------------------------------------------------------------------
# 스트리밍 tap (로깅용 누적)
# ---------------------------------------------------------------------------


def _tap_chunk(chunk: dict, content_parts: list[str], tool_calls: dict[int, dict], tap: dict) -> None:
    """SSE 청크 하나를 로깅용으로 누적한다 (클라이언트 전달과 무관).

    텍스트 델타·tool_calls 델타를 모으고, 마지막 usage 청크와 응답 id를 포착한다.
    """
    if chunk.get("usage"):
        tap["usage"] = chunk["usage"]
    if chunk.get("id") and "id" not in tap:
        tap["id"] = chunk["id"]
    for choice in chunk.get("choices") or []:
        delta = choice.get("delta") or {}
        if delta.get("content"):
            content_parts.append(delta["content"])
        for d in delta.get("tool_calls") or []:
            idx = d.get("index", 0)
            slot = tool_calls.setdefault(
                idx, {"id": None, "type": "function", "function": {"name": "", "arguments": ""}}
            )
            if d.get("id"):
                slot["id"] = d["id"]
            if d.get("type"):
                slot["type"] = d["type"]
            fn = d.get("function") or {}
            if fn.get("name"):
                slot["function"]["name"] += fn["name"]
            if fn.get("arguments"):
                slot["function"]["arguments"] += fn["arguments"]


def _finish_reason(chunk: dict) -> str | None:
    for choice in chunk.get("choices") or []:
        if choice.get("finish_reason"):
            return choice["finish_reason"]
    return None


# ---------------------------------------------------------------------------
# HTTP 호출
# ---------------------------------------------------------------------------


async def call_chat_non_stream(
    body: dict, slot_id: int, base_url: str, timeout: int = 600
) -> dict:
    """업스트림 /v1/chat/completions(non-stream)을 호출하고 JSON을 그대로 반환한다."""
    req = prepare_upstream_body(body, slot_id)
    async with make_client(base_url, timeout) as client:
        try:
            r = await client.post("/v1/chat/completions", json=req)
        except httpx.HTTPError as e:
            write_upstream_raw_log(
                {**_raw_log_base(body, slot_id, base_url, "non_stream"),
                 "request": req, "error": repr(e)}
            )
            from ..errors import upstream_error
            raise upstream_error(f"Upstream chat error: {e}")
    try:
        data = r.json()
    except ValueError:
        data = {"_raw_text": r.text}
    write_upstream_raw_log(
        {**_raw_log_base(body, slot_id, base_url, "non_stream"),
         "status_code": r.status_code, "request": req, "response": data}
    )
    if r.is_success:
        return data
    raise _map_upstream_error(r.status_code, data)


async def call_chat_stream(
    body: dict, slot_id: int, base_url: str, tap: dict, timeout: int = 600
):
    """업스트림 SSE를 payload 무변형으로 yield하면서 ``tap``에 로깅용 상태를 채운다.

    ``tap``은 호출부가 스트림 종료(또는 클라이언트 단절) 후 읽는다:
    ``content`` / ``tool_calls`` / ``usage`` / ``finish_reason`` / ``id``.
    동시에 업스트림 원본 요청과 누적 출력을 raw 로그로 남긴다.
    """
    req = prepare_upstream_body(body, slot_id)
    content_parts: list[str] = []
    tool_calls: dict[int, dict] = {}
    finish_reason: str | None = None
    chunk_count = 0
    error: str | None = None
    try:
        async with make_client(base_url, timeout) as client:
            async with client.stream("POST", "/v1/chat/completions", json=req) as r:
                if r.status_code >= 400:
                    text = (await r.aread()).decode("utf-8", "replace")
                    error = f"status={r.status_code} body={text}"
                    r.raise_for_status()  # httpx.HTTPError → 호출부 except에서 정리
                async for line in r.aiter_lines():
                    line = line.strip()
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        yield "data: [DONE]\n\n"
                        continue
                    try:
                        chunk = json.loads(payload)
                    except json.JSONDecodeError:
                        yield f"data: {payload}\n\n"
                        continue
                    chunk_count += 1
                    _tap_chunk(chunk, content_parts, tool_calls, tap)
                    if (fr := _finish_reason(chunk)) is not None:
                        finish_reason = fr
                    # payload 원본을 그대로 전달 (무변형 패스스루)
                    yield f"data: {payload}\n\n"
    except BaseException as e:  # noqa: BLE001 — 기록 후 그대로 재전파
        if error is None:
            error = repr(e)
        raise
    finally:
        tap["content"] = "".join(content_parts)
        tap["tool_calls"] = [tool_calls[i] for i in sorted(tool_calls)] or None
        tap["finish_reason"] = finish_reason
        write_upstream_raw_log(
            {**_raw_log_base(body, slot_id, base_url, "stream"),
             "request": req,
             "response_content": tap["content"],
             "tool_calls": tap["tool_calls"],
             "usage": tap.get("usage"),
             "finish_reason": finish_reason,
             "chunk_count": chunk_count,
             "error": error}
        )
