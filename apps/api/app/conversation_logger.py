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


def _raw_log_path(dt: datetime) -> Path:
    log_dir = Path(settings.CONVERSATION_LOG_DIR)
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / f"raw-{dt.strftime('%Y-%m-%d')}.jsonl"


def write_upstream_raw_log(entry: dict) -> None:
    """업스트림(llama-server/ollama) 원본 요청·응답을 raw-YYYY-MM-DD.jsonl로 기록한다.

    서비스 로직의 OpenAI 포맷 변환 이전 raw 데이터를 그대로 남긴다.
    네이티브 prompt(도구 정의가 프롬프트에 들어갔는지)와 모델 원문 출력
    (`<tool_call>` 등 변환 과정에서 가려지는 출력)을 확인하는 용도다.
    한 줄이 한 번의 업스트림 호출에 해당한다.
    """
    if not settings.RAW_UPSTREAM_LOG:
        return
    now = datetime.now(timezone.utc)
    record = {"timestamp": now.isoformat(), **entry}
    try:
        with _raw_log_path(now).open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except Exception:
        logger.exception("업스트림 raw 로그 저장 실패")


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
        "tool_calls": tool_calls,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "latency_ms": latency_ms,
        "ttft_ms": ttft_ms,
    }
    try:
        with _log_path(now).open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        logger.exception("대화 로그 저장 실패")
