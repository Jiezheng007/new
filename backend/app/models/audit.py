from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.user import utcnow


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    actor_username: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String(32), default="", nullable=False, index=True)
    target_id: Mapped[str] = mapped_column(String(64), default="", nullable=False, index=True)
    result: Mapped[str] = mapped_column(String(16), default="success", nullable=False, index=True)
    detail: Mapped[str] = mapped_column(Text, default="", nullable=False)
    ip_address: Mapped[str] = mapped_column(String(45), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )
