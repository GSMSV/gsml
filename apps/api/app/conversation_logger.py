"""LLM 대화 내역을 날짜별 JSONL 파일로 기록한다.

{CONVERSATION_LOG_DIR}/YYYY-MM-DD.jsonl 형식으로 저장되며,
한 줄이 한 요청(request)에 해당한다.
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from .config import settings

logger = logging.getLogger(__name__)


def _log_path(dt: datetime) -> Path:
    log_dir = Path(settings.CONVERSATION_LOG_DIR)
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / f"{dt.strftime('%Y-%m-%d')}.jsonl"


def write_conversation_log(
    *,
    request_id: str,
    user_id: str,
    user_email: str,
    user_name: str,
    model: str,
    conv_id: str,
    messages: list[dict],
    response_text: str,
    prompt_tokens: int,
    completion_tokens: int,
    latency_ms: int,
    ttft_ms: int | None,
    stream: bool,
    reasoning_text: str | None = None,
    tool_calls: list[dict] | None = None,
) -> None:
    now = datetime.now(timezone.utc)
    entry = {
        "timestamp": now.isoformat(),
        "request_id": request_id,
        "user_id": user_id,
        "user_email": user_email,
        "user_name": user_name,
        "model": model,
        "conv_id": conv_id,
        "stream": stream,
        "messages": messages,
        "response": response_text,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "latency_ms": latency_ms,
        "ttft_ms": ttft_ms,
    }
    # 업스트림이 분리해 준 경우에만 기록한다 (없는 모델에서 빈 키가 생기지 않도록).
    if reasoning_text:
        entry["reasoning"] = reasoning_text
    if tool_calls:
        entry["tool_calls"] = tool_calls
    try:
        with _log_path(now).open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        logger.exception("대화 로그 저장 실패")
