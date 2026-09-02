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
