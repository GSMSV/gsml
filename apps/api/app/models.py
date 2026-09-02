import uuid
from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    oauth_sub: Mapped[str] = mapped_column(String, unique=True, index=True)
    email: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)

    # 단위는 크레딧(float). 토큰이 아니다 — app/pricing.py 참조.
    usage_limit: Mapped[float] = mapped_column(Float)
    current_usage: Mapped[float] = mapped_column(Float, default=0.0)
    max_concurrent: Mapped[int] = mapped_column(Integer)

    # 토큰 한도 → 크레딧 한도 1회 환산이 끝났는지 표시 (db.init_db 참조)
    credit_migrated: Mapped[int] = mapped_column(Integer, default=1)

    last_reset_date: Mapped[date] = mapped_column(Date, default=lambda: _utcnow().date())
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    api_key: Mapped["ApiKey | None"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    key_hash: Mapped[str] = mapped_column(String, unique=True, index=True)
    key_prefix: Mapped[str] = mapped_column(String)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    user: Mapped[User] = relationship(back_populates="api_key")


class RequestLog(Base):
    __tablename__ = "request_logs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    model: Mapped[str] = mapped_column(String)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    # prompt_tokens 중 업스트림 KV 캐시에서 재사용된 몫 (부분집합)
    cached_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    # 요청 시점 단가로 확정된 청구액. 단가가 바뀌어도 과거 집계가 흔들리지 않도록 저장한다.
    credits_charged: Mapped[float] = mapped_column(Float, default=0.0)
    status_code: Mapped[int] = mapped_column(Integer)
    latency_ms: Mapped[int] = mapped_column(Integer)
    ttft_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str | None] = mapped_column(String, nullable=True)  # "api" | "web"
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
