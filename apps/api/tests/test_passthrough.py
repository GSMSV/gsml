"""openai_passthrough 전송 계층 테스트.

httpx MockTransport로 업스트림 /v1/chat/completions를 가짜로 세워
body 준비·non-stream usage 추출·stream 패스스루+tap을 검증한다.
"""
import json

import httpx
import pytest

from app.errors import OpenAIError
from app.upstream import openai_passthrough as op


def _mock_client(handler):
    """make_client 대체: MockTransport를 단 AsyncClient를 반환하는 팩토리."""
    def factory(base_url, timeout=600):
        return httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url=base_url, timeout=timeout
        )
    return factory


def _sse(*chunks: dict) -> str:
    """dict 청크들을 OpenAI SSE 스트림 문자열로 직렬화 ([DONE] 포함)."""
    lines = [f"data: {json.dumps(c)}" for c in chunks]
    lines.append("data: [DONE]")
    return "\n\n".join(lines) + "\n\n"


# ── body 준비 ───────────────────────────────────────────────────────────────


def test_prepare_injects_control_fields_and_passes_tools_through():
    tools = [{"type": "function", "function": {"name": "get_weather"}}]
    body = {
        "model": "qwen",
        "messages": [{"role": "user", "content": "hi"}],
        "tools": tools,
        "tool_choice": "auto",
        "response_format": {"type": "json_object"},
        "stream": True,
    }
    out = op.prepare_upstream_body(body, slot_id=3)

    assert out["id_slot"] == 3
    assert out["cache_prompt"] is True
    assert out["n"] == 1
    assert out["stream_options"]["include_usage"] is True
    # 도구·포맷은 무변형 통과
    assert out["tools"] == tools
    assert out["tool_choice"] == "auto"
    assert out["response_format"] == {"type": "json_object"}
    # 원본 body는 변형되지 않음
    assert "id_slot" not in body and "n" not in body and "stream_options" not in body


def test_prepare_non_stream_omits_stream_options():
    out = op.prepare_upstream_body({"model": "q", "messages": []}, slot_id=0)
    assert "stream_options" not in out
    assert out["id_slot"] == 0


def test_prepare_respects_slot_pinning_off(monkeypatch):
    monkeypatch.setattr(op.settings, "UPSTREAM_SLOT_PINNING", False)
    out = op.prepare_upstream_body({"model": "q", "messages": []}, slot_id=7)
    assert "id_slot" not in out
    assert out["cache_prompt"] is True  # cache_prompt prefix-match로 폴백


# ── non-stream ──────────────────────────────────────────────────────────────


async def test_call_non_stream_returns_upstream_json_and_injects_slot(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        captured["path"] = request.url.path
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-x",
                "object": "chat.completion",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "hello"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 11, "completion_tokens": 3, "total_tokens": 14},
            },
        )

    monkeypatch.setattr(op, "make_client", _mock_client(handler))
    resp = await op.call_chat_non_stream(
        {"model": "qwen", "messages": [{"role": "user", "content": "hi"}]}, 2, "http://up"
    )

    assert resp["usage"]["prompt_tokens"] == 11
    assert resp["choices"][0]["message"]["content"] == "hello"
    assert captured["path"] == "/v1/chat/completions"
    assert captured["body"]["id_slot"] == 2
    assert captured["body"]["cache_prompt"] is True
    assert captured["body"]["n"] == 1


async def test_call_non_stream_returns_tool_calls(monkeypatch):
    tool_calls = [
        {
            "id": "call_1",
            "type": "function",
            "function": {"name": "get_weather", "arguments": '{"city":"seoul"}'},
        }
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-tc",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": None, "tool_calls": tool_calls},
                        "finish_reason": "tool_calls",
                    }
                ],
                "usage": {"prompt_tokens": 50, "completion_tokens": 9, "total_tokens": 59},
            },
        )

    monkeypatch.setattr(op, "make_client", _mock_client(handler))
    resp = await op.call_chat_non_stream({"model": "qwen", "messages": []}, 0, "http://up")
    choice = resp["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    assert choice["message"]["tool_calls"][0]["function"]["name"] == "get_weather"


async def test_call_non_stream_maps_4xx_preserving_status(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "invalid tools schema"}})

    monkeypatch.setattr(op, "make_client", _mock_client(handler))
    with pytest.raises(OpenAIError) as ei:
        await op.call_chat_non_stream({"model": "q", "messages": []}, 0, "http://up")
    assert ei.value.status_code == 400
    assert "invalid tools schema" in ei.value.message


async def test_call_non_stream_maps_5xx_to_502(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal boom")

    monkeypatch.setattr(op, "make_client", _mock_client(handler))
    with pytest.raises(OpenAIError) as ei:
        await op.call_chat_non_stream({"model": "q", "messages": []}, 0, "http://up")
    assert ei.value.status_code == 502


# ── stream ──────────────────────────────────────────────────────────────────


async def test_call_stream_passthrough_and_text_tap(monkeypatch):
    sse = _sse(
        {"id": "chatcmpl-1", "choices": [{"index": 0, "delta": {"role": "assistant", "content": "He"}}]},
        {"id": "chatcmpl-1", "choices": [{"index": 0, "delta": {"content": "llo"}}]},
        {"id": "chatcmpl-1", "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
        {"id": "chatcmpl-1", "choices": [], "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7}},
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=sse, headers={"content-type": "text/event-stream"})

    monkeypatch.setattr(op, "make_client", _mock_client(handler))
    tap: dict = {}
    out = [
        chunk
        async for chunk in op.call_chat_stream(
            {"model": "q", "messages": [], "stream": True}, 1, "http://up", tap
        )
    ]
    joined = "".join(out)

    # 클라이언트로 전달된 스트림에 원본 페이로드 + [DONE]가 그대로 흐른다
    assert joined.count("data: ") == 5  # 4 chunks + [DONE]
    assert joined.rstrip().endswith("data: [DONE]")
    # 로깅용 tap 누적
    assert tap["content"] == "Hello"
    assert tap["usage"]["total_tokens"] == 7
    assert tap["finish_reason"] == "stop"
    assert tap["id"] == "chatcmpl-1"
    assert tap["tool_calls"] is None


async def test_call_stream_accumulates_tool_call_deltas(monkeypatch):
    sse = _sse(
        {"choices": [{"index": 0, "delta": {"tool_calls": [
            {"index": 0, "id": "call_1", "type": "function",
             "function": {"name": "get_weather", "arguments": ""}}]}}]},
        {"choices": [{"index": 0, "delta": {"tool_calls": [
            {"index": 0, "function": {"arguments": '{"city":'}}]}}]},
        {"choices": [{"index": 0, "delta": {"tool_calls": [
            {"index": 0, "function": {"arguments": '"seoul"}'}}]}}]},
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
        {"choices": [], "usage": {"prompt_tokens": 40, "completion_tokens": 8, "total_tokens": 48}},
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=sse, headers={"content-type": "text/event-stream"})

    monkeypatch.setattr(op, "make_client", _mock_client(handler))
    tap: dict = {}
    async for _ in op.call_chat_stream(
        {"model": "q", "messages": [], "stream": True}, 1, "http://up", tap
    ):
        pass

    assert tap["finish_reason"] == "tool_calls"
    assert tap["content"] == ""
    assert len(tap["tool_calls"]) == 1
    tc = tap["tool_calls"][0]
    assert tc["id"] == "call_1"
    assert tc["type"] == "function"
    assert tc["function"]["name"] == "get_weather"
    assert tc["function"]["arguments"] == '{"city":"seoul"}'


async def test_call_stream_raises_on_upstream_error(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="busy")

    monkeypatch.setattr(op, "make_client", _mock_client(handler))
    tap: dict = {}
    with pytest.raises(httpx.HTTPStatusError):
        async for _ in op.call_chat_stream(
            {"model": "q", "messages": [], "stream": True}, 1, "http://up", tap
        ):
            pass
