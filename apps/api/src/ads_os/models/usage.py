"""Учёт потребления (v0.4 §13).

Платёжная система в MVP не подключается, но считать потребление нужно с первого
дня: восстановить историю задним числом невозможно, а LLM-затраты на проект —
прямое требование v0.3 §64.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Index, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base, OrganizationScoped, Timestamps, UUIDPrimaryKey


class UsageService(StrEnum):
    AI = "ai"
    CRAWLER = "crawler"
    EXTERNAL_API = "external_api"
    STORAGE = "storage"
    REPORT = "report"


class UsageUnit(StrEnum):
    TOKENS = "tokens"
    REQUESTS = "requests"
    PAGES = "pages"
    BYTES = "bytes"


class UsageEvent(UUIDPrimaryKey, Timestamps, OrganizationScoped, Base):
    __tablename__ = "usage_events"
    __table_args__ = (
        # Учёт читается агрегатами по организации и периоду — индекс под это.
        Index("ix_usage_events_org_created", "organization_id", "created_at"),
    )

    project_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )

    service: Mapped[UsageService] = mapped_column(
        SAEnum(UsageService, name="usage_service", native_enum=False, length=20), nullable=False
    )
    operation: Mapped[str] = mapped_column(String(120), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(16, 4), nullable=False)
    unit: Mapped[UsageUnit] = mapped_column(
        SAEnum(UsageUnit, name="usage_unit", native_enum=False, length=20), nullable=False
    )
    estimated_cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 6), nullable=True)

    #: Провайдер, модель, назначение вызова. Персональные данные сюда не
    #: попадают: это метаданные учёта, а не копия запроса (v0.4 §2.3).
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
