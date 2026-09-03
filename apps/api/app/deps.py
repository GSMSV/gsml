from datetime import datetime, timezone

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from .db import get_db
from .errors import expired_api_key, invalid_api_key
from .models import ApiKey, User
from .security import decode_jwt, hash_api_key


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    """JWT(대시보드) 인증."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    user_id = decode_jwt(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def get_admin_user(
    user: User = Depends(get_current_user),
) -> User:
    """JWT 인증 + admin role 요구. `/api/admin/*` 전용."""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


def get_api_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    """API Key(OpenAI 프록시) 인증."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise invalid_api_key()
    plain = authorization.split(" ", 1)[1].strip()
    if not plain.startswith("sk-"):
        raise invalid_api_key()

    key = db.query(ApiKey).filter(ApiKey.key_hash == hash_api_key(plain)).one_or_none()
    if not key:
        raise invalid_api_key()
    if key.expires_at < datetime.now(timezone.utc).replace(tzinfo=None):
        raise expired_api_key()

    user = db.get(User, key.user_id)
    if not user:
        raise invalid_api_key()
    return user


def get_user_any(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    """JWT 또는 API Key 양쪽 인증 허용.

    웹 대시보드(JWT)와 OpenAI 호환 클라이언트(sk- API Key) 모두 지원하는
    엔드포인트에서 사용한다. (예: GET /v1/models)
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise invalid_api_key()
    token = authorization.split(" ", 1)[1].strip()

    if token.startswith("sk-"):
        # API Key 인증
        key = db.query(ApiKey).filter(ApiKey.key_hash == hash_api_key(token)).one_or_none()
        if not key:
            raise invalid_api_key()
        if key.expires_at < datetime.now(timezone.utc).replace(tzinfo=None):
            raise expired_api_key()
        user = db.get(User, key.user_id)
        if not user:
            raise invalid_api_key()
        return user
    else:
        # JWT 인증
        user_id = decode_jwt(token)
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")
        user = db.get(User, user_id)
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return user
