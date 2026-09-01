"""llama-server OpenAI 호환 엔드포인트(/v1/chat/completions) 클라이언트.

프롬프트 렌더(모델에 내장된 Jinja 템플릿 적용), reasoning/tool call 파싱,
tools grammar 강제를 모두 llama-server에 맡긴다. 프록시는 라우팅에 필요한
파라미터만 얹고 응답 본문은 손대지 않는다.

슬롯 지정 파라미터 이름은 `id_slot`이다. 구버전 llama.cpp의 `slot_id`는 지금
소스에 존재하지 않으므로, 그 이름으로 보내면 조용히 무시되고 서버가 프롬프트
LCP 유사도로 슬롯을 임의 선택한다.
"""
import json
import logging

import httpx

from .client import make_client
from .instance_node import InstanceNode

logger = logging.getLogger(__name__)

_CHAT_PATH = "/v1/chat/completions"


def apply_routing(body: dict, slot_id: int) -> dict:
    """업스트림 body에 슬롯 고정 파라미터를 얹은 새 dict를 반환한다.

    llama.cpp의 oaicompat 파서는 알려지지 않은 키를 그대로 하위 completion
    파라미터로 넘기므로, OAI 엔드포인트에서도 id_slot/cache_prompt가 먹는다.
    """
    return {**body, "id_slot": slot_id, "cache_prompt": True}


def _error_event(status_code: int, detail: str) -> str:
    """스트리밍 도중 업스트림 실패를 알리는 OpenAI 포맷 SSE 라인."""
    payload = {
        "error": {
            "message": f"Upstream error {status_code}: {detail}",
            "type": "api_error",
            "code": "upstream_error",
        }
    }
    return f"data: {json.dumps(payload, ensure_ascii=False)}"


async def call_chat_non_stream(
    body: dict, slot_id: int, node: InstanceNode, timeout: int = 600
) -> tuple[int, dict]:
    """(status_code, json_body)를 반환한다.

    업스트림 에러 응답도 이미 OpenAI 포맷이므로 그대로 돌려주고, 전달 여부는
    호출부가 판단한다. 전송 자체가 실패했거나 본문이 JSON이 아니면 502.
    """
    from ..errors import upstream_error

    async with make_client(node.url, timeout) as client:
        try:
            r = await client.post(_CHAT_PATH, json=apply_routing(body, slot_id))
        except httpx.HTTPError as e:
            raise upstream_error(f"Upstream chat completion error: {e}")
    try:
        return r.status_code, r.json()
    except json.JSONDecodeError:
        raise upstream_error(f"Upstream returned non-JSON body ({r.status_code}).")


async def call_chat_stream(body: dict, slot_id: int, node: InstanceNode, timeout: int = 600):
    """업스트림 SSE를 `(raw_line, parsed)` 튜플로 yield한다.

    raw_line은 클라이언트로 그대로 흘려보낼 한 줄이고, parsed는 회계·로깅용으로
    파싱한 dict다 (data 라인이 아니거나 `[DONE]`이면 None).
    """
    async with make_client(node.url, timeout) as client:
        async with client.stream(
            "POST", _CHAT_PATH, json=apply_routing(body, slot_id)
        ) as r:
            if r.status_code != 200:
                detail = (await r.aread()).decode("utf-8", "replace")
                logger.warning(
                    "Upstream stream failed on %s: %d %s", node.url, r.status_code, detail[:200]
                )
                yield _error_event(r.status_code, detail[:200]), None
                yield "data: [DONE]", None
                return
            async for line in r.aiter_lines():
                if not line:
                    continue
                parsed = None
                if line.startswith("data: "):
                    payload = line[6:].strip()
                    if payload and payload != "[DONE]":
                        try:
                            parsed = json.loads(payload)
                        except json.JSONDecodeError:
                            pass
                yield line, parsed


def merge_tool_call_deltas(acc: dict[int, dict], deltas: list[dict]) -> None:
    """스트리밍 tool_calls 조각을 index별로 acc에 누적한다 (로깅용)."""
    for d in deltas:
        idx = int(d.get("index", 0))
        cur = acc.setdefault(
            idx, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}
        )
        if d.get("id"):
            cur["id"] = d["id"]
        if d.get("type"):
            cur["type"] = d["type"]
        fn = d.get("function") or {}
        if fn.get("name"):
            cur["function"]["name"] = fn["name"]
        if fn.get("arguments"):
            cur["function"]["arguments"] += fn["arguments"]
