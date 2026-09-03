from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .config import settings

TZ = ZoneInfo(settings.APP_TIMEZONE)


def today_local() -> date:
    return datetime.now(TZ).date()


def next_midnight_local() -> datetime:
    now = datetime.now(TZ)
    tomorrow = (now + timedelta(days=1)).date()
    return datetime.combine(tomorrow, datetime.min.time(), tzinfo=TZ)


def today_start_utc_naive() -> datetime:
    """오늘 00:00(APP_TIMEZONE 기준)을 naive UTC로 변환한다.

    `RequestLog.created_at`은 naive UTC로 저장되므로(app/db.py 참조), local-day
    경계로 그 컬럼을 필터링하려면 이 값과 비교해야 한다.
    """
    start_local = datetime.combine(today_local(), datetime.min.time(), tzinfo=TZ)
    return start_local.astimezone(timezone.utc).replace(tzinfo=None)
