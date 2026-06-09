"""ORM model package.

Importing every module here is the canonical way to make sure SQLAlchemy
registers all tables with ``Base.metadata`` - including models that are only
referenced indirectly (e.g. via relationships from another module).
"""
from app.models.alert import Alert  # noqa: F401
from app.models.analysis import AnalysisResult  # noqa: F401
from app.models.audit import AuditLog  # noqa: F401
from app.models.datasource import DataSource, OpinionItem  # noqa: F401
from app.models.report import ReportTask  # noqa: F401
from app.models.rule import RiskThreshold, SensitiveKeyword, SubjectKeyword  # noqa: F401
from app.models.ticket import Ticket  # noqa: F401
from app.models.user import Role, User  # noqa: F401
