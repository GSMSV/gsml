"""OpenAI 호환 프록시.

지원: GET /v1/models, POST /v1/chat/completions (stream + non-stream).

conv_id 기반 스티키 라우팅은 Balancer가 담당한다.
모든 추론 요청은 업스트림 /v1/chat/completions로 얇게 패스스루된다
(tools / tool_choice / response_format 무변형 통과).
"""
import asyncio
import time
import uuid

import httpx
from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.orm import Session

from ..concurrency import acquire_slot, release, try_acquire
from ..config import settings
from ..conversation_logger import write_conversation_log
from ..db import get_db
from ..deps import get_api_user, get_user_any
from ..errors import insufficient_quota, service_unavailable, upstream_error
from ..models import RequestLog, User
from ..upstream import get_balancer
from ..upstream.balancer import RouteEntry
from ..upstream.client import make_client
from ..upstream.openai_passthrough import call_chat_non_stream, call_chat_stream
from ..upstream.token_count import count_messages

router = APIRouter(prefix="/v1", tags=["openai"])

# 클라이언트가 보낼 수 없는 서버 제어 필드 (덮어쓰거나 strip).
_SERVER_CONTROLLED = {"user"}


def _conv_id(user_id: str, x_conversation_id: str | None) -> str:
    """user_id로 스코핑된 대화 키를 반환한다.

    다른 사용자가 동일한 X-Conversation-ID를 보내도 슬롯이 겹치지 않도록
    user_id를 접두사로 붙인다.
    """
    cid = (x_conversation_id or "").strip() or "default"
    return f"{user_id}:{cid}"


def _quota_headers(user: User) -> dict[str, str]:
    remaining = max(0, user.usage_limit - user.current_usage)
    return {
        "X-RateLimit-Limit-Tokens": str(user.usage_limit),
        "X-RateLimit-Remaining-Tokens": str(remaining),
    }


def _log_and_charge(
    db: Session,
    user: User,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    status_code: int,
    latency_ms: int,
    ttft_ms: int | None,
    source: str = "api",
) -> None:
    user.current_usage += prompt_tokens + completion_tokens
    db.add(
        RequestLog(
            user_id=user.id,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            status_code=status_code,
            latency_ms=latency_ms,
            ttft_ms=ttft_ms,
            source=source,
        )
    )
    db.commit()


@router.get("/models")
async def list_models(user: User = Depends(get_user_any)):
    """업스트림 /v1/models 응답을 그대로 프록시."""
    alive = get_balancer().alive_nodes
    if not alive:
        raise service_unavailable("No available inference instances.")
    base_url = alive[0].url
    async with make_client(base_url, settings.UPSTREAM_TIMEOUT) as client:
        try:
            r = await client.get("/v1/models")
        except httpx.HTTPError as e:
            raise upstream_error(f"Failed to reach upstream: {e}")
    return JSONResponse(
        status_code=r.status_code, content=r.json(), headers=_quota_headers(user)
    )


@router.post("/chat/completions")
async def chat_completions(
    request: Request,
    user: User = Depends(get_api_user),
    db: Session = Depends(get_db),
    x_conversation_id: str | None = Header(default=None),
):
    body = await request.json()
    model = body.get("model", "")
    messages = body.get("messages", [])
    is_stream = bool(body.get("stream", False))

    # 사전 quota 검사
    if user.current_usage >= user.usage_limit:
        raise insufficient_quota()

    # 서버 제어 필드 정리 (id_slot / cache_prompt / n / stream_options 주입은
    # openai_passthrough.prepare_upstream_body가 담당)
    for k in _SERVER_CONTROLLED:
        body.pop(k, None)
    body["user"] = user.id

    conv_id = _conv_id(user.id, x_conversation_id)
    headers = _quota_headers(user)

    # Balancer에서 인스턴스 + 슬롯 획득
    try:
        route = get_balancer().acquire(conv_id)
    except RuntimeError:
        raise service_unavailable("No available inference instances.")

    if not is_stream:
        async with acquire_slot(user.id, user.max_concurrent):
            try:
                return await _do_passthrough_non_stream(db, user, body, headers, route, messages, conv_id)
            finally:
                get_balancer().release(conv_id)

    try_acquire(user.id, user.max_concurrent)
    try:
        return await _do_passthrough_stream(db, user, body, messages, headers, route, conv_id)
    except BaseException:
        release(user.id)
        get_balancer().release(conv_id)
        raise


# ---------------------------------------------------------------------------
# /v1/chat/completions 패스스루 헬퍼
# ---------------------------------------------------------------------------


async def _do_passthrough_non_stream(
    db: Session,
    user: User,
    body: dict,
    headers: dict,
    route: RouteEntry,
    messages: list | None = None,
    conv_id: str = "",
    source: str = "api",
) -> JSONResponse:
    started = time.perf_counter()
    model = body.get("model", "")
    msgs = messages or body.get("messages", [])
    resp = await call_chat_non_stream(
        body, route.slot_id, route.node.url, settings.UPSTREAM_TIMEOUT
    )
    latency_ms = int((time.perf_counter() - started) * 1000)
    usage = resp.get("usage") or {}
    pt = int(usage.get("prompt_tokens") or 0) or count_messages(msgs)
    ct = int(usage.get("completion_tokens") or 0)
    choice = (resp.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    _log_and_charge(db, user, model, pt, ct, 200, latency_ms, None, source)
    write_conversation_log(
        request_id=resp.get("id", f"chatcmpl-{uuid.uuid4().hex}"),
        user_id=user.id,
        user_email=user.email,
        user_name=user.name,
        model=model,
        conv_id=conv_id,
        messages=msgs,
        response_text=msg.get("content") or "",
        tool_calls=msg.get("tool_calls"),
        prompt_tokens=pt,
        completion_tokens=ct,
        latency_ms=latency_ms,
        ttft_ms=None,
        stream=False,
    )
    out = {**headers, "X-RateLimit-Remaining-Tokens": str(max(0, user.usage_limit - user.current_usage))}
    return JSONResponse(status_code=200, content=resp, headers=out)


async def _do_passthrough_stream(
    db: Session,
    user: User,
    body: dict,
    messages: list,
    headers: dict,
    route: RouteEntry,
    conv_id: str,
    source: str = "api",
) -> StreamingResponse:
    started = time.perf_counter()
    model = body.get("model", "")
    state = {"ttft_ms": None}
    tap: dict = {}

    async def gen():
        try:
            async for sse in call_chat_stream(
                body, route.slot_id, route.node.url, tap, settings.UPSTREAM_TIMEOUT
            ):
                if state["ttft_ms"] is None:
                    state["ttft_ms"] = int((time.perf_counter() - started) * 1000)
                yield sse.encode("utf-8")
        except (asyncio.CancelledError, httpx.HTTPError):
            pass
        finally:
            try:
                usage = tap.get("usage") or {}
                pt = int(usage.get("prompt_tokens") or 0) or count_messages(messages)
                ct = int(usage.get("completion_tokens") or 0)
                total_latency_ms = int((time.perf_counter() - started) * 1000)
                _log_and_charge(
                    db,
                    user,
                    model,
                    pt,
                    ct,
                    200,
                    total_latency_ms,
                    state["ttft_ms"],
                    source,
                )
                write_conversation_log(
                    request_id=tap.get("id", f"chatcmpl-{uuid.uuid4().hex}"),
                    user_id=user.id,
                    user_email=user.email,
                    user_name=user.name,
                    model=model,
                    conv_id=conv_id,
                    messages=messages,
                    response_text=tap.get("content", ""),
                    tool_calls=tap.get("tool_calls"),
                    prompt_tokens=pt,
                    completion_tokens=ct,
                    latency_ms=total_latency_ms,
                    ttft_ms=state["ttft_ms"],
                    stream=True,
                )
            finally:
                get_balancer().release(conv_id)
                release(user.id)

    out_headers = dict(headers)
    out_headers["Content-Type"] = "text/event-stream"
    out_headers["Cache-Control"] = "no-cache"
    out_headers["Connection"] = "keep-alive"
    return StreamingResponse(gen(), media_type="text/event-stream", headers=out_headers)
