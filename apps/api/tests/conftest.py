"""pytest 공통 설정.

editable 설치 없이 실행될 때를 대비해 apps/api를 sys.path에 추가하고,
테스트 중 업스트림 raw 로그가 디스크에 쌓이지 않도록 끈다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from app.config import settings  # noqa: E402


@pytest.fixture(autouse=True)
def _no_raw_log(monkeypatch):
    monkeypatch.setattr(settings, "RAW_UPSTREAM_LOG", False)
