from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings

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


# 추가 순서는 무관하다. 각각 독립적으로 시도되고 실패(=이미 존재)는 무시된다.
# 기존 유저의 usage_limit/current_usage를 토큰 단위 → 크레딧 단위로 바꾸는 작업은
# 여기서 자동으로 하지 않는다. 배포자가 직접 UPDATE 쿼리를 수동으로 실행한다.
_ADD_COLUMN_STATEMENTS = (
    "ALTER TABLE request_logs ADD COLUMN source VARCHAR",
    "ALTER TABLE request_logs ADD COLUMN cached_tokens INTEGER DEFAULT 0",
    "ALTER TABLE request_logs ADD COLUMN credits_charged FLOAT DEFAULT 0",
    "ALTER TABLE users ADD COLUMN role VARCHAR DEFAULT 'general'",
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
