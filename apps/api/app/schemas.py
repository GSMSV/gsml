from datetime import datetime

from pydantic import BaseModel


class CallbackRequest(BaseModel):
    code: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class MeResponse(BaseModel):
    id: str
    email: str
    name: str
    role: str
    # 단위는 크레딧(float). 토큰이 아니다.
    usage_limit: float
    current_usage: float
    percent_used: float
    max_concurrent: int


class KeyInfo(BaseModel):
    prefix: str
    expires_at: datetime
    created_at: datetime


class IssuedKeyResponse(BaseModel):
    api_key: str  # 평문 — 1회 노출
    prefix: str
    expires_at: datetime


class UsageTodayResponse(BaseModel):
    used: float
    limit: float
    percent_used: float
    reset_at: datetime


class UsageHistoryItem(BaseModel):
    date: str
    credits: float
    total_tokens: int
    request_count: int


class AdminUserItem(BaseModel):
    id: str
    email: str
    name: str
    role: str
    # 단위는 크레딧(float). 토큰이 아니다.
    usage_limit: float
    current_usage: float
    percent_used: float
    max_concurrent: int
    api_key_prefix: str | None
    api_key_expires_at: datetime | None
    created_at: datetime


class AdminUserUpdate(BaseModel):
    usage_limit: float | None = None
    current_usage: float | None = None
    max_concurrent: int | None = None
    role: str | None = None


class AdminTopUser(BaseModel):
    id: str
    name: str
    email: str
    current_usage: float
    usage_limit: float
    percent_used: float


class AdminStatsResponse(BaseModel):
    total_users: int
    admin_count: int
    active_users_today: int
    # 단위는 크레딧(float). 토큰이 아니다.
    total_credits_today: float
    total_requests_today: int
    total_tokens_today: int
    daily_history: list[UsageHistoryItem]
    top_users: list[AdminTopUser]
