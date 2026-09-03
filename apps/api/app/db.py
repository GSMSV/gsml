import logging

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings

logger = logging.getLogger(__name__)

connect_args = {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(settings.DATABASE_URL, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    from . import models  # noqa: F401  ensure models are imported before create_all

    Base.metadata.create_all(bind=engine)

    # create_all은 없는 테이블만 만들 뿐 컬럼을 추가하지 않는다.
    # 기존 data/gsml.db를 위해 누락 컬럼을 하나씩 시도하고, 이미 있으면 무시한다.
    with engine.connect() as conn:
        for stmt in _ADD_COLUMN_STATEMENTS:
            try:
                conn.execute(text(stmt))
                conn.commit()
            except Exception:
                conn.rollback()  # 이미 존재하면 무시

        _backfill_credit_limits(conn)


# 추가 순서는 무관하다. 각각 독립적으로 시도되고 실패(=이미 존재)는 무시된다.
_ADD_COLUMN_STATEMENTS = (
    "ALTER TABLE request_logs ADD COLUMN source VARCHAR",
    "ALTER TABLE request_logs ADD COLUMN cached_tokens INTEGER DEFAULT 0",
    "ALTER TABLE request_logs ADD COLUMN credits_charged FLOAT DEFAULT 0",
    # DEFAULT 0 → 기존 유저만 0으로 표시되어 아래 백필 대상이 된다.
    # 신규 유저는 모델 기본값(1)으로 삽입되므로 다시 환산되지 않는다.
    "ALTER TABLE users ADD COLUMN credit_migrated INTEGER DEFAULT 0",
    "ALTER TABLE users ADD COLUMN role VARCHAR DEFAULT 'general'",
)


def _backfill_credit_limits(conn) -> None:
    """토큰 한도를 쓰던 기존 유저를 크레딧 한도로 1회 환산한다.

    토큰과 크레딧은 서로 환산 계수가 없는 단위라(단가에 따라 달라진다) 기존 값을
    비례 변환하지 않고 DEFAULT_CREDIT_LIMIT으로 재설정한다. 운영자가 개별 조정한
    한도가 있었다면 이 시점에 초기화되므로, 배포 전 data/gsml.db 백업을 권장한다.
    current_usage는 어차피 매일 자정에 리셋되므로 0으로 밀어도 손실이 없다.
    """
    try:
        result = conn.execute(
            text(
                "UPDATE users SET usage_limit = :limit, current_usage = 0, "
                "credit_migrated = 1 WHERE credit_migrated = 0"
            ),
            {"limit": settings.DEFAULT_CREDIT_LIMIT},
        )
        conn.commit()
    except Exception:
        conn.rollback()
        logger.exception("크레딧 한도 백필 실패")
        return
    if result.rowcount:
        logger.warning(
            "Migrated %d user(s) from token quota to credit quota (limit=%s)",
            result.rowcount,
            settings.DEFAULT_CREDIT_LIMIT,
        )


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
