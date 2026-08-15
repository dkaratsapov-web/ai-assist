"""Результат аудита сайта."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base, OrganizationScoped, Timestamps, UUIDPrimaryKey


class ModuleStatus(StrEnum):
    """Состояние работы модуля (v0.3 §5).

    Общее для всех долгих операций: аудита, сбора семантики, анализа
    конкурентов. Интерфейс показывает их одинаково, поэтому и в базе они
    называются одинаково.
    """

    NOT_STARTED = "not_started"
    QUEUED = "queued"
    RUNNING = "running"
    NEEDS_REVIEW = "needs_review"
    COMPLETED = "completed"
    FAILED = "failed"


class SiteAudit(UUIDPrimaryKey, Timestamps, OrganizationScoped, Base):
    """Один запуск аудита.

    История сохраняется целиком, а не перезаписывается: нужно видеть, что
    менялось на сайте между запусками (v0.3 §62). Текущим считается последний
    завершённый.
    """

    __tablename__ = "site_audits"
    __table_args__ = (
        # Последний аудит проекта запрашивается на каждом открытии экрана.
        Index("ix_site_audits_project_created", "project_id", "created_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )

    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    status: Mapped[ModuleStatus] = mapped_column(
        SAEnum(ModuleStatus, name="module_status", native_enum=False, length=20),
        default=ModuleStatus.QUEUED,
        nullable=False,
    )

    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    verdict: Mapped[str | None] = mapped_column(String(32), nullable=True)

    #: Разбор по категориям и список находок. Структура задаётся модулем
    #: аудита, здесь она хранится как есть — переносить её в отдельные таблицы
    #: незачем: она читается целиком и не участвует в выборках.
    categories: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    issues: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)

    metrica_counter: Mapped[str | None] = mapped_column(String(20), nullable=True)
    final_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    #: Причина отказа простым языком. Наружу не уходит ни трассировка, ни текст
    #: исключения (v0.3 §137).
    error_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def is_finished(self) -> bool:
        return self.status in (ModuleStatus.COMPLETED, ModuleStatus.FAILED)
