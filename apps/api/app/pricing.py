"""토큰 사용량 → 크레딧 환산.

크레딧은 float이고, 단가는 토큰 100만 개당 크레딧으로 설정한다(`Settings.PRICE_*_PER_1M`).
과금 항목은 셋으로 나뉜다.

- input        : 업스트림이 실제로 프리필한 프롬프트 토큰
- cached_input : 업스트림 KV 캐시에서 재사용된 프롬프트 토큰 (기본 무료)
- output       : 생성 토큰. reasoning 토큰도 업스트림 usage상 여기 포함된다

업스트림(llama-server)의 `usage.prompt_tokens`는 캐시된 토큰을 **포함한** 전체 프롬프트
길이이고 `usage.prompt_tokens_details.cached_tokens`가 그 부분집합이다. 따라서 새로
프리필된 토큰은 둘의 차이이며, 두 값을 그냥 더하면 캐시분을 두 번 청구하게 된다.
"""
import logging

from .config import settings

logger = logging.getLogger(__name__)

_PER_MILLION = 1_000_000

# prompt_tokens_details가 없는 구버전 업스트림 경고를 프로세스당 한 번만 남기기 위한 플래그
_missing_details_warned = False


def cached_tokens_from_usage(usage: dict) -> int:
    """업스트림 usage에서 캐시 히트 토큰 수를 읽는다.

    필드를 주지 않는 구버전 llama-server에서는 0이 되고, 캐시 히트분이 전부 신규
    입력으로 과금된다. 조용히 넘어가면 배포 사고를 놓치므로 한 번 경고를 남긴다.
    """
    global _missing_details_warned
    details = usage.get("prompt_tokens_details")
    if details is None:
        if usage and not _missing_details_warned:
            _missing_details_warned = True
            logger.warning(
                "Upstream usage has no prompt_tokens_details; "
                "cached input will be billed as fresh input. Update llama-server."
            )
        return 0
    return int(details.get("cached_tokens") or 0)


def charge_credits(prompt_tokens: int, cached_tokens: int, completion_tokens: int) -> float:
    """이번 요청에 청구할 크레딧을 계산한다.

    cached_tokens는 prompt_tokens의 부분집합이므로 범위를 넘지 않도록 잘라낸다.
    """
    cached = max(0, min(cached_tokens, prompt_tokens))
    fresh = max(0, prompt_tokens - cached)
    total = (
        fresh * settings.PRICE_INPUT_PER_1M
        + cached * settings.PRICE_CACHED_INPUT_PER_1M
        + max(0, completion_tokens) * settings.PRICE_OUTPUT_PER_1M
    )
    return total / _PER_MILLION


def percent_used(used: float, limit: float) -> float:
    """한도 대비 사용률(%). 한도가 0 이하면 0.0."""
    if limit <= 0:
        return 0.0
    return round(used / limit * 100, 1)
