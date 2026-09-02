from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from .config import settings
from .db import SessionLocal
from .models import RequestLog, User
from .timezone_util import TZ, today_local


def reset_daily_usage() -> None:
    today = today_local()
    with SessionLocal() as db:
        db.query(User).update(
            {User.current_usage: 0.0, User.last_reset_date: today}, synchronize_session=False
        )
        db.commit()


def purge_old_logs() -> None:
    cutoff = datetime.utcnow() - timedelta(days=settings.REQUEST_LOG_RETENTION_DAYS)
    with SessionLocal() as db:
        db.query(RequestLog).filter(RequestLog.created_at < cutoff).delete(
            synchronize_session=False
        )
        db.commit()


def catch_up_resets() -> None:
    """기동 시 다운타임 동안 누락된 자정 리셋을 보정."""
    today = today_local()
    with SessionLocal() as db:
        db.query(User).filter(User.last_reset_date < today).update(
            {User.current_usage: 0.0, User.last_reset_date: today}, synchronize_session=False
        )
        db.commit()


def start_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=TZ)
    scheduler.add_job(reset_daily_usage, CronTrigger(hour=0, minute=0, timezone=TZ))
    scheduler.add_job(purge_old_logs, CronTrigger(hour=0, minute=5, timezone=TZ))
    scheduler.start()
    return scheduler
