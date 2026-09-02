from fastapi import APIRouter, Depends

from ..deps import get_current_user
from ..models import User
from ..pricing import percent_used
from ..schemas import MeResponse

router = APIRouter(prefix="/api/me", tags=["me"])


@router.get("", response_model=MeResponse)
def me(user: User = Depends(get_current_user)) -> MeResponse:
    return MeResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        usage_limit=user.usage_limit,
        current_usage=round(user.current_usage, 6),
        percent_used=percent_used(user.current_usage, user.usage_limit),
        max_concurrent=user.max_concurrent,
    )
