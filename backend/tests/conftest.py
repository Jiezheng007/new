"""Test fixtures: isolated SQLite per-test, FastAPI app, HTTP client, seeded data."""
from __future__ import annotations

import os
import tempfile
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("SECRET_KEY", "test-secret-key")

from app.core.config import get_settings  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.db.session import (  # noqa: E402
    SQLITE_CONNECT_TIMEOUT_S,
    Base,
    get_db,
    register_sqlite_pragmas,
)
from app.main import create_app  # noqa: E402
from app.models.datasource import DataSource  # noqa: E402
from app.models.role_codes import ROLE_SEEDS, RoleCode  # noqa: E402
from app.models.rule import RiskThreshold, SensitiveKeyword, SubjectKeyword  # noqa: E402
from app.models.user import Role, User  # noqa: E402


@pytest.fixture()
def test_db_url() -> Generator[str, None, None]:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    url = f"sqlite:///{tmp.name}"
    yield url
    try:
        os.unlink(tmp.name)
    except OSError:
        pass


@pytest.fixture()
def app(test_db_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", test_db_url)
    monkeypatch.setenv("SECRET_KEY", "test-secret-key")
    get_settings.cache_clear()

    from app.db import session as session_module
    from app.services import bootstrap as bootstrap_module

    test_engine = create_engine(
        test_db_url,
        connect_args={"check_same_thread": False, "timeout": SQLITE_CONNECT_TIMEOUT_S},
    )
    # Mirror the production PRAGMAs (WAL + busy_timeout) so concurrency
    # tests exercise the same configuration the running app uses.
    register_sqlite_pragmas(test_engine)
    TestSession = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)
    session_module.engine = test_engine
    session_module.SessionLocal = TestSession
    bootstrap_module.engine = test_engine
    Base.metadata.create_all(bind=test_engine)

    with TestSession() as db:
        for code, name, description in ROLE_SEEDS:
            db.add(Role(code=code, name=name, description=description))
        db.commit()
        admin_role = db.query(Role).filter(Role.code == RoleCode.ADMIN).one()
        risk_role = db.query(Role).filter(Role.code == RoleCode.RISK_CONTROL).one()
        handler_role = db.query(Role).filter(Role.code == RoleCode.HANDLER).one()
        auditor_role = db.query(Role).filter(Role.code == RoleCode.AUDITOR).one()
        viewer_role = db.query(Role).filter(Role.code == RoleCode.VIEWER).one()

        db.add_all([
            User(username="admin", full_name="管理员", password_hash=hash_password("admin123"), role_id=admin_role.id),
            User(username="risk", full_name="风控", password_hash=hash_password("risk123"), role_id=risk_role.id),
            User(username="handler", full_name="处置", password_hash=hash_password("handler123"), role_id=handler_role.id),
            User(username="auditor", full_name="审计", password_hash=hash_password("auditor123"), role_id=auditor_role.id),
            User(username="viewer", full_name="查看", password_hash=hash_password("viewer123"), role_id=viewer_role.id),
            User(username="disabled", full_name="停用", password_hash=hash_password("disabled123"), is_active=False, role_id=viewer_role.id),
        ])
        db.add_all([
            RiskThreshold(level="low", min_score=0),
            RiskThreshold(level="medium", min_score=30),
            RiskThreshold(level="high", min_score=60),
            RiskThreshold(level="severe", min_score=85),
        ])
        db.add_all([
            SensitiveKeyword(keyword="重大", category="通用", severity="high", remark="测试夹具"),
            SensitiveKeyword(keyword="严重", category="通用", severity="high", remark="测试夹具"),
            SensitiveKeyword(keyword="安全", category="公共", severity="severe", remark="测试夹具"),
            SensitiveKeyword(keyword="事故", category="公共", severity="severe", remark="测试夹具"),
            SensitiveKeyword(keyword="违规", category="合规", severity="medium", remark="测试夹具"),
            SensitiveKeyword(keyword="投诉", category="消费", severity="low", remark="测试夹具"),
        ])
        db.add_all([
            SubjectKeyword(keyword="监管部门", category="监管", remark="测试夹具"),
            SubjectKeyword(keyword="某品牌", category="消费", remark="测试夹具"),
            SubjectKeyword(keyword="某公司", category="企业", remark="测试夹具"),
        ])
        db.add(DataSource(
            code="demo_static",
            name="内置演示数据源",
            source_type="static_demo",
            url="",
            weight=1.0,
            is_enabled=True,
            description="测试夹具内置的演示数据源",
        ))
        db.add_all([
            DataSource(code="import_csv", name="CSV 导入聚合", source_type="csv", url="", weight=1.0, is_enabled=True, description="测试夹具"),
            DataSource(code="import_json", name="JSON 导入聚合", source_type="json_import", url="", weight=1.0, is_enabled=True, description="测试夹具"),
        ])
        db.commit()

    application = create_app()

    def _override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    application.dependency_overrides[get_db] = _override_get_db
    yield application


@pytest.fixture()
def client(app) -> Generator[TestClient, None, None]:
    c = TestClient(app)
    try:
        yield c
    finally:
        c.close()


def login_as(client: TestClient, username: str, password: str) -> None:
    res = client.post("/api/auth/login", json={"username": username, "password": password})
    assert res.status_code == 200, res.text
