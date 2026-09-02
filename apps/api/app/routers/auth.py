import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import User
from ..schemas import CallbackRequest, TokenResponse
from ..security import create_jwt

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/callback", response_model=TokenResponse)
async def oauth_callback(
    payload: CallbackRequest, db: Session = Depends(get_db)
) -> TokenResponse:
    # 1) code → access_token
    async with httpx.AsyncClient(timeout=15) as client:
        token_resp = await client.post(
            f"{settings.OAUTH_AUTH_BASE}/v1/oauth/token",
            json={
                "grant_type": "authorization_code",
                "code": payload.code,
                "client_id": settings.OAUTH_CLIENT_ID,
                "client_secret": settings.OAUTH_CLIENT_SECRET,
                "redirect_uri": settings.OAUTH_REDIRECT_URI,
            },
        )
        access_token = token_resp.json().get("access_token")
        if not access_token:
            raise HTTPException(status_code=401, detail="No access token from OAuth")

        # 2) userinfo
        info_resp = await client.get(
            f"{settings.OAUTH_RESOURCE_BASE}/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if info_resp.status_code != 200:
            raise HTTPException(status_code=401, detail="Failed to fetch userinfo")
        info = info_resp.json()

    sub = str(info.get("sub") or info.get("id") or info.get("email"))
    email = info.get("email", "")
    name = info.get("name") or info.get("nickname") or email

    if not sub:
        raise HTTPException(status_code=401, detail="Userinfo missing identifier")

    # 3) upsert (최초 1회만 프로필 저장)
    user = db.query(User).filter(User.oauth_sub == sub).one_or_none()
    if user is None:
        user = User(
            oauth_sub=sub,
            email=email,
            name=name,
            usage_limit=settings.DEFAULT_CREDIT_LIMIT,
            max_concurrent=settings.DEFAULT_MAX_CONCURRENT,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    token, expires_in = create_jwt(user.id)
    return TokenResponse(access_token=token, expires_in=expires_in)
