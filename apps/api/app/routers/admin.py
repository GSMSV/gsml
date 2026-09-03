from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_admin_user
from ..models import RequestLog, User
from ..pricing import percent_used
from ..schemas import (
    AdminStatsResponse,
    AdminTopUser,
    AdminUserItem,
    AdminUserUpdate,
    UsageHistoryItem,
)
from ..timezone_util import today_start_utc_naive

router = APIRouter(prefix="/api/admin", tags=["admin"])

VALID_ROLES = {"general", "admin"}


def _to_item(user: User) -> AdminUserItem:
    key = user.api_key
    return AdminUserItem(
        id=user.id,
        email=user.email,
        name=user.name,
        role=user.role,
        usage_limit=user.usage_limit,
        current_usage=round(user.current_usage, 6),
        percent_used=percent_used(user.current_usage, user.usage_limit),
        max_concurrent=user.max_concurrent,
        api_key_prefix=key.key_prefix if key else None,
        api_key_expires_at=key.expires_at if key else None,
        created_at=user.created_at,
    )


@router.get("/users", response_model=list[AdminUserItem])
def list_users(
    q: str | None = Query(default=None),
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> list[AdminUserItem]:
    query = db.query(User)
    if q:
        like = f"%{q}%"
        query = query.filter((User.email.ilike(like)) | (User.name.ilike(like)))
    users = query.order_by(User.created_at.desc()).all()
    return [_to_item(u) for u in users]


@router.patch("/users/{user_id}", response_model=AdminUserItem)
def update_user(
    user_id: str,
    payload: AdminUserUpdate,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> AdminUserItem:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if payload.usage_limit is not None:
        if payload.usage_limit < 0:
            raise HTTPException(status_code=400, detail="usage_limit must be >= 0")
        user.usage_limit = payload.usage_limit
    if payload.current_usage is not None:
        if payload.current_usage < 0:
            raise HTTPException(status_code=400, detail="current_usage must be >= 0")
        user.current_usage = payload.current_usage
    if payload.max_concurrent is not None:
        if payload.max_concurrent < 1:
            raise HTTPException(status_code=400, detail="max_concurrent must be >= 1")
        user.max_concurrent = payload.max_concurrent
    if payload.role is not None:
        if payload.role not in VALID_ROLES:
            raise HTTPException(status_code=400, detail="Invalid role")
        if user.id == admin.id:
            raise HTTPException(status_code=400, detail="Cannot change your own role")
        user.role = payload.role

    db.commit()
    db.refresh(user)
    return _to_item(user)


@router.get("/stats", response_model=AdminStatsResponse)
def stats(
    days: int = Query(default=7, ge=1, le=90),
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> AdminStatsResponse:
    users = db.query(User).all()
    total_users = len(users)
    admin_count = sum(1 for u in users if u.role == "admin")
    active_users_today = sum(1 for u in users if u.current_usage > 0)
    # current_usage는 로컬 자정마다 리셋되는 "오늘 사용량"이므로(app/scheduler.py 참조)
    # RequestLog를 다시 날짜별로 스캔하지 않고 그대로 합산한다.
    total_credits_today = round(sum(u.current_usage for u in users), 6)

    today_start = today_start_utc_naive()
    rows_today = (
        db.query(RequestLog).filter(RequestLog.created_at >= today_start).all()
    )
    total_requests_today = len(rows_today)
    total_tokens_today = sum(r.prompt_tokens + r.completion_tokens for r in rows_today)

    since = datetime.utcnow() - timedelta(days=days)
    rows = db.query(RequestLog).filter(RequestLog.created_at >= since).all()
    bucket: dict[str, dict[str, float]] = defaultdict(
        lambda: {"credits": 0.0, "tokens": 0, "count": 0}
    )
    for r in rows:
        d = r.created_at.date().isoformat()
        bucket[d]["credits"] += r.credits_charged or 0.0
        bucket[d]["tokens"] += r.prompt_tokens + r.completion_tokens
        bucket[d]["count"] += 1
    daily_history = [
        UsageHistoryItem(
            date=d,
            credits=round(v["credits"], 6),
            total_tokens=int(v["tokens"]),
            request_count=int(v["count"]),
        )
        for d, v in sorted(bucket.items())
    ]

    top = sorted(users, key=lambda u: u.current_usage, reverse=True)[:5]
    top_users = [
        AdminTopUser(
            id=u.id,
            name=u.name,
            email=u.email,
            current_usage=round(u.current_usage, 6),
            usage_limit=u.usage_limit,
            percent_used=percent_used(u.current_usage, u.usage_limit),
        )
        for u in top
    ]

    return AdminStatsResponse(
        total_users=total_users,
        admin_count=admin_count,
        active_users_today=active_users_today,
        total_credits_today=total_credits_today,
        total_requests_today=total_requests_today,
        total_tokens_today=total_tokens_today,
        daily_history=daily_history,
        top_users=top_users,
    )
