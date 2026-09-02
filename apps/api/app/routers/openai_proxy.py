"""OpenAI 호환 프록시.

지원: GET /v1/models, POST /v1/chat/completions (stream + non-stream).

conv_id 기반 스티키 라우팅은 Balancer가 담당하고, 추론 요청은 업스트림의
OpenAI 호환 엔드포인트로 그대로 전달된다. 프롬프트 템플릿 적용과 reasoning /
tool call 파싱은 llama-server가 하므로 프록시는 응답 본문을 변형하지 않는다.
"""
import asyncio
import logging
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
from ..pricing import cached_tokens_from_usage, charge_credits
from ..upstream import get_balancer
from ..upstream.balancer import RouteEntry
from ..upstream.client import make_client
from ..upstream.llama_chat import (
    call_chat_non_stream,
    call_chat_stream,
    merge_tool_call_deltas,
)
from ..upstream.token_count import count_messages

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["openai"])

# 클라이언트가 보낼 수 없는 서버 제어 필드 (덮어쓰거나 strip).
# id_slot/cache_prompt는 Balancer가 정하는 값이다. 클라이언트가 직접 슬롯을
# 지정하면 다른 사용자의 대화가 붙어 있는 슬롯을 밀어낼 수 있으므로 반드시 버린다.
# slot_id는 구버전 llama.cpp의 이름 — 지금은 무시되지만 같이 막아둔다.
# 이 넷 외에는 body를 그대로 넘긴다. llama.cpp가 모르는 필드는 조용히 버리고,
# grammar/samplers/mirostat*/dry_*/xtc_* 같은 확장 파라미터는 의도적으로 열어둔다.
_SERVER_CONTROLLED = {"user", "id_slot", "cache_prompt", "slot_id"}


def _conv_id(user_id: str, x_conversation_id: str | None) -> str:
    """user_id로 스코핑된 대화 키를 반환한다.

    다른 사용자가 동일한 X-Conversation-ID를 보내도 슬롯이 겹치지 않도록
    user_id를 접두사로 붙인다.
    """
    cid = (x_conversation_id or "").strip() or "default"
    return f"{user_id}:{cid}"


def _quota_headers(user: User) -> dict[str, str]:
    """남은 크레딧을 헤더로 노출한다.

    -Tokens 쌍은 토큰 과금 시절의 이름이지만 기존 클라이언트가 읽고 있을 수 있어
    같은 크레딧 값을 미러링한 채로 남겨둔다. 새로 붙는 쪽은 -Credits를 읽을 것.
    """
    limit = f"{user.usage_limit:.6f}"
    remaining = f"{max(0.0, user.usage_limit - user.current_usage):.6f}"
    return {
        "X-RateLimit-Limit-Credits": limit,
        "X-RateLimit-Remaining-Credits": remaining,
        "X-RateLimit-Limit-Tokens": limit,  # deprecated alias
        "X-RateLimit-Remaining-Tokens": remaining,  # deprecated alias
    }


def _log_and_charge(
    db: Session,
    user: User,
    model: str,
    prompt_tokens: int,
    cached_tokens: int,
    completion_tokens: int,
    status_code: int,
    latency_ms: int,
    ttft_ms: int | None,
    source: str = "api",
) -> None:
    """크레딧을 청구하고 RequestLog를 남긴다. 스트림/비스트림 공통 과금 지점.

    쿼터는 요청 전에 검사하고 후에 청구하므로 마지막 요청은 한도를 넘길 수 있다.
    초과분은 청구하지 않고 잔량만 차감해 정확히 '소진 완료' 상태로 만든다.
    부동소수 누적 오차로 한도에 미세하게 못 미쳐 429가 안 나가는 일이 없도록,
    한도를 넘긴 경우에는 더하지 않고 usage_limit을 그대로 대입한다.
    """
    credits = charge_credits(prompt_tokens, cached_tokens, completion_tokens)
    remaining = user.usage_limit - user.current_usage
    if credits >= remaining:
        credits = max(0.0, remaining)
        user.current_usage = user.usage_limit
    else:
        user.current_usage += credits
    db.add(
        RequestLog(
            user_id=user.id,
            model=model,
            prompt_tokens=prompt_tokens,
            cached_tokens=cached_tokens,
            completion_tokens=completion_tokens,
            credits_charged=credits,
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

    # 서버 제어 필드 정리 + 스트리밍 usage 강제
    for k in _SERVER_CONTROLLED:
        body.pop(k, None)
    body["user"] = user.id
    if is_stream:
        opts = body.get("stream_options") or {}
        opts["include_usage"] = True
        body["stream_options"] = opts

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
                return await _do_chat_non_stream(db, user, body, headers, route, messages, conv_id)
            finally:
                get_balancer().release(conv_id)

    try_acquire(user.id, user.max_concurrent)
    try:
        return await _do_chat_stream(db, user, body, messages, headers, route, conv_id)
    except BaseException:
        release(user.id)
        get_balancer().release(conv_id)
        raise


# ---------------------------------------------------------------------------
# 업스트림 /v1/chat/completions 경로 헬퍼
# ---------------------------------------------------------------------------


async def _do_chat_non_stream(
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
    status, resp = await call_chat_non_stream(
        body, route.slot_id, route.node, settings.UPSTREAM_TIMEOUT
    )
    latency_ms = int((time.perf_counter() - started) * 1000)

    # 업스트림 에러 본문은 이미 OpenAI 포맷이므로 그대로 전달한다. 토큰은 청구하지 않는다.
    if status != 200:
        logger.warning("Upstream chat completion failed on %s: %d", route.node.url, status)
        return JSONResponse(status_code=status, content=resp, headers=headers)

    u = resp.get("usage") or {}
    pt = int(u.get("prompt_tokens") or 0) or count_messages(messages or body.get("messages", []))
    ct = int(u.get("completion_tokens") or 0)
    # cached_tokens는 prompt_tokens의 부분집합이다 (더하지 말 것).
    cached = cached_tokens_from_usage(u)
    _log_and_charge(db, user, model, pt, cached, ct, 200, latency_ms, None, source)

    msg = (resp.get("choices") or [{}])[0].get("message") or {}
    write_conversation_log(
        request_id=resp.get("id") or f"chatcmpl-{uuid.uuid4().hex}",
        user_id=user.id,
        user_email=user.email,
        user_name=user.name,
        model=model,
        conv_id=conv_id,
        messages=messages or body.get("messages", []),
        response_text=msg.get("content") or "",
        reasoning_text=msg.get("reasoning_content"),
        tool_calls=msg.get("tool_calls"),
        prompt_tokens=pt,
        completion_tokens=ct,
        latency_ms=latency_ms,
        ttft_ms=None,
        stream=False,
    )
    # 방금 청구한 만큼을 반영한 잔량으로 갱신해서 돌려준다.
    return JSONResponse(status_code=200, content=resp, headers=_quota_headers(user))


async def _do_chat_stream(
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
    fallback_cid = f"chatcmpl-{uuid.uuid4().hex}"
    state = {
        "ttft_ms": None,
        "prompt_tokens": 0,
        "cached_tokens": 0,
        "completion_tokens": 0,
        "request_id": "",
    }
    response_parts: list[str] = []
    reasoning_parts: list[str] = []
    tool_call_acc: dict[int, dict] = {}

    async def gen():
        try:
            async for line, chunk in call_chat_stream(
                body, route.slot_id, route.node, settings.UPSTREAM_TIMEOUT
            ):
                # 청크는 회계·로깅용으로만 읽고, 클라이언트에는 원본 라인을 그대로 흘린다.
                if chunk is not None:
                    if state["ttft_ms"] is None:
                        state["ttft_ms"] = int((time.perf_counter() - started) * 1000)
                    if not state["request_id"]:
                        state["request_id"] = chunk.get("id") or ""
                    if usage := chunk.get("usage"):
                        state["prompt_tokens"] = int(usage.get("prompt_tokens") or 0)
                        state["cached_tokens"] = cached_tokens_from_usage(usage)
                        state["completion_tokens"] = int(usage.get("completion_tokens") or 0)
                    for choice in chunk.get("choices") or []:
                        delta = choice.get("delta") or {}
                        if content := delta.get("content"):
                            response_parts.append(content)
                        if reasoning := delta.get("reasoning_content"):
                            reasoning_parts.append(reasoning)
                        if deltas := delta.get("tool_calls"):
                            merge_tool_call_deltas(tool_call_acc, deltas)
                yield f"{line}\n\n".encode("utf-8")
        except (asyncio.CancelledError, httpx.HTTPError):
            pass
        finally:
            try:
                # usage 청크 전에 끊기면 tiktoken 근사로 폴백한다. 이 경로에서는
                # 캐시 히트를 알 수 없어 cached=0이 되고, 그만큼 비싸게 청구된다.
                pt = state["prompt_tokens"] or count_messages(messages)
                cached = state["cached_tokens"]
                ct = state["completion_tokens"]
                total_latency_ms = int((time.perf_counter() - started) * 1000)
                _log_and_charge(
                    db,
                    user,
                    model,
                    pt,
                    cached,
                    ct,
                    200,
                    total_latency_ms,
                    state["ttft_ms"],
                    source,
                )
                write_conversation_log(
                    request_id=state["request_id"] or fallback_cid,
                    user_id=user.id,
                    user_email=user.email,
                    user_name=user.name,
                    model=model,
                    conv_id=conv_id,
                    messages=messages,
                    response_text="".join(response_parts),
                    reasoning_text="".join(reasoning_parts) or None,
                    tool_calls=[tool_call_acc[i] for i in sorted(tool_call_acc)] or None,
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
