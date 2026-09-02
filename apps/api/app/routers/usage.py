from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import RequestLog, User
from ..pricing import percent_used
from ..schemas import UsageHistoryItem, UsageTodayResponse
from ..timezone_util import next_midnight_local

router = APIRouter(prefix="/api/usage", tags=["usage"])


@router.get("/today", response_model=UsageTodayResponse)
def usage_today(user: User = Depends(get_current_user)) -> UsageTodayResponse:
    return UsageTodayResponse(
        used=round(user.current_usage, 6),
        limit=user.usage_limit,
        percent_used=percent_used(user.current_usage, user.usage_limit),
        reset_at=next_midnight_local(),
    )


@router.get("/history", response_model=list[UsageHistoryItem])
def usage_history(
    days: int = Query(default=7, ge=1, le=90),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[UsageHistoryItem]:
    since = datetime.utcnow() - timedelta(days=days)
    rows = (
        db.query(RequestLog)
        .filter(RequestLog.user_id == user.id, RequestLog.created_at >= since)
        .all()
    )
    # 크레딧은 요청 시점 단가로 확정된 credits_charged를 합산한다. 토큰에서 다시
    # 계산하면 단가를 바꾼 뒤 과거 집계가 통째로 흔들린다.
    bucket: dict[str, dict[str, float]] = defaultdict(
        lambda: {"credits": 0.0, "tokens": 0, "count": 0}
    )
    for r in rows:
        d = r.created_at.date().isoformat()
        bucket[d]["credits"] += r.credits_charged or 0.0
        bucket[d]["tokens"] += r.prompt_tokens + r.completion_tokens
        bucket[d]["count"] += 1
    items = [
        UsageHistoryItem(
            date=d,
            credits=round(v["credits"], 6),
            total_tokens=int(v["tokens"]),
            request_count=int(v["count"]),
        )
        for d, v in sorted(bucket.items())
    ]
    return items
