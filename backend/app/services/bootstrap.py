"""Database initialization: create tables, seed roles, seed baseline risk rules and demo sources, create bootstrap admin and demo users."""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.session import Base, engine
from app.models.datasource import DataSource
from app.models.role_codes import ROLE_SEEDS, RoleCode
from app.models.rule import RiskThreshold, SensitiveKeyword, SubjectKeyword
from app.models.user import Role, User


_DEMO_USERS: list[tuple[str, str, str, str]] = [
    (RoleCode.RISK_CONTROL, "risk", "风控演示账号", "risk123"),
    (RoleCode.HANDLER, "handler", "处置演示账号", "handler123"),
    (RoleCode.AUDITOR, "auditor", "审计演示账号", "auditor123"),
    (RoleCode.VIEWER, "viewer", "查看演示账号", "viewer123"),
]


# Default risk threshold cut-offs. min_score is the inclusive lower bound of
# the band; the bands must be sorted ascending and end with a value that
# covers the maximum possible score (a hard ceiling is not stored).
DEFAULT_RISK_THRESHOLDS: list[tuple[str, int]] = [
    ("low", 0),
    ("medium", 30),
    ("high", 60),
    ("severe", 85),
]


# Default sensitive / subject keywords so the demo and the risk-scoring
# pipeline have a working rule set on first boot. Admins can edit or
# disable any of these through the rule page; bootstrap only inserts
# rows that are not already present.
DEFAULT_SENSITIVE_KEYWORDS: list[tuple[str, str, str]] = [
    ("重大", "通用", "high"),
    ("严重", "通用", "high"),
    ("安全", "公共", "severe"),
    ("事故", "公共", "severe"),
    ("违规", "合规", "medium"),
    ("投诉", "消费", "low"),
    ("泄露", "公共", "high"),
    ("造假", "合规", "severe"),
    ("召回", "消费", "high"),
]

DEFAULT_SUBJECT_KEYWORDS: list[tuple[str, str]] = [
    ("监管部门", "监管"),
    ("某品牌", "消费"),
    ("某公司", "企业"),
    ("示例科技公司", "企业"),
]


# One built-in static demo data source ships with the app so the course
# demo works without any external network. The connector is identified by
# source_type="static_demo" and returns a fixed set of opinion items.
_DEMO_STATIC_SOURCE: dict[str, object] = {
    "code": "demo_static",
    "name": "内置演示数据源",
    "source_type": "static_demo",
    "url": "",
    "weight": 1.0,
    "description": "随系统内置的演示数据,用于课堂演示与无网络环境的兜底展示。",
}

# Shared sink sources for CSV/JSON imports so re-uploads dedup naturally
# against the (source_id, content_hash) uniqueness constraint.
_IMPORT_SOURCES: list[dict[str, object]] = [
    {
        "code": "import_csv",
        "name": "CSV 导入聚合",
        "source_type": "csv",
        "description": "所有 CSV 导入汇聚到的虚拟数据源,便于重复上传时自动去重。",
    },
    {
        "code": "import_json",
        "name": "JSON 导入聚合",
        "source_type": "json_import",
        "description": "所有 JSON 导入汇聚到的虚拟数据源,便于重复上传时自动去重。",
    },
]


def init_db() -> None:
    """Create tables, seed roles, risk thresholds, demo data source, and bootstrap users."""
    from app.models import audit, datasource, rule, user  # noqa: F401 - ensure model registration

    Base.metadata.create_all(bind=engine)
    _ensure_datasource_keyword_columns()
    with Session(engine) as db:
        _seed_roles(db)
        db.commit()
        _seed_risk_thresholds(db)
        db.commit()
        _seed_sensitive_keywords(db)
        db.commit()
        _seed_subject_keywords(db)
        db.commit()
        _seed_demo_data_source(db)
        db.commit()
        _seed_import_sources(db)
        db.commit()
        _seed_admin(db)
        db.commit()
        _seed_demo_users(db)
        db.commit()


def _ensure_datasource_keyword_columns() -> None:
    """Add keyword-monitoring columns for existing SQLite databases.

    This project does not use Alembic. ``create_all`` creates the columns for
    fresh databases, but existing local demo databases need small additive
    migrations so the app can start after a model change.
    """
    if not str(engine.url).startswith("sqlite"):
        return
    wanted = {
        "query": "TEXT NOT NULL DEFAULT ''",
        "fetch_interval_minutes": "INTEGER NOT NULL DEFAULT 60",
        "max_items_per_fetch": "INTEGER NOT NULL DEFAULT 50",
        "config_json": "TEXT NOT NULL DEFAULT '{}'",
    }
    with engine.begin() as conn:
        existing = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(data_sources)")}
        for column, ddl in wanted.items():
            if column not in existing:
                conn.execute(text(f"ALTER TABLE data_sources ADD COLUMN {column} {ddl}"))


def _seed_roles(db: Session) -> None:
    existing = {role.code for role in db.query(Role).all()}
    for code, name, description in ROLE_SEEDS:
        if code in existing:
            continue
        db.add(Role(code=code, name=name, description=description))


def _seed_risk_thresholds(db: Session) -> None:
    existing = {row.level for row in db.query(RiskThreshold).all()}
    for level, min_score in DEFAULT_RISK_THRESHOLDS:
        if level in existing:
            continue
        db.add(RiskThreshold(level=level, min_score=min_score))


def _seed_sensitive_keywords(db: Session) -> None:
    existing = {row.keyword for row in db.query(SensitiveKeyword).all()}
    for keyword, category, severity in DEFAULT_SENSITIVE_KEYWORDS:
        if keyword in existing:
            continue
        db.add(SensitiveKeyword(keyword=keyword, category=category, severity=severity))


def _seed_subject_keywords(db: Session) -> None:
    existing = {row.keyword for row in db.query(SubjectKeyword).all()}
    for keyword, category in DEFAULT_SUBJECT_KEYWORDS:
        if keyword in existing:
            continue
        db.add(SubjectKeyword(keyword=keyword, category=category))


def _seed_demo_data_source(db: Session) -> None:
    code = _DEMO_STATIC_SOURCE["code"]
    if db.query(DataSource).filter(DataSource.code == code).first():
        return
    db.add(DataSource(
        code=code,
        name=_DEMO_STATIC_SOURCE["name"],
        source_type=_DEMO_STATIC_SOURCE["source_type"],
        url=_DEMO_STATIC_SOURCE["url"],
        weight=_DEMO_STATIC_SOURCE["weight"],
        is_enabled=True,
        description=_DEMO_STATIC_SOURCE["description"],
    ))


def _seed_import_sources(db: Session) -> None:
    for spec in _IMPORT_SOURCES:
        if db.query(DataSource).filter(DataSource.code == spec["code"]).first():
            continue
        db.add(DataSource(
            code=spec["code"],
            name=spec["name"],
            source_type=spec["source_type"],
            url="",
            weight=1.0,
            is_enabled=True,
            description=spec["description"],
        ))


def _seed_admin(db: Session) -> None:
    settings = get_settings()
    username = settings.bootstrap_admin_username
    password = settings.bootstrap_admin_password
    if not username or not password:
        return
    user = db.query(User).filter(User.username == username).one_or_none()
    if user is not None:
        return
    admin_role = db.query(Role).filter(Role.code == RoleCode.ADMIN).one_or_none()
    if admin_role is None:
        return
    db.add(
        User(
            username=username,
            full_name="Bootstrap Admin",
            password_hash=hash_password(password),
            is_active=True,
            role_id=admin_role.id,
        )
    )


def _seed_demo_users(db: Session) -> None:
    """Create one demo account per non-admin role so the Web UI is fully demoable."""
    for role_code, username, full_name, password in _DEMO_USERS:
        if db.query(User).filter(User.username == username).first():
            continue
        role = db.query(Role).filter(Role.code == role_code).one_or_none()
        if role is None:
            continue
        db.add(
            User(
                username=username,
                full_name=full_name,
                password_hash=hash_password(password),
                is_active=True,
                role_id=role.id,
            )
        )
