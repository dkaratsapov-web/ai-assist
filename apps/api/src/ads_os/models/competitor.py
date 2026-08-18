"""Конкурент проекта и результат его разбора."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base, OrganizationScoped, Timestamps, UUIDPrimaryKey
from .audit import ModuleStatus


class Competitor(UUIDPrimaryKey, Timestamps, OrganizationScoped, Base):
    """Сайт конкурента, добавленный к проекту.

    В отличие от аудита, история здесь не копится: конкурент — это запись,
    которую перепроверяют, а не серия запусков. Нужен снимок «как сейчас», а
    не летопись чужих правок.
    """

    __tablename__ = "competitors"
    __table_args__ = (
        # Один и тот же адрес не добавляется к проекту дважды: дубль ломает
        # само сравнение — признак начинает считаться за двоих.
        UniqueConstraint("project_id", "url", name="uq_competitors_project_url"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )

    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    #: Название, введённое пользователем, или заголовок страницы после разбора.
    title: Mapped[str | None] = mapped_column(String(300), nullable=True)

    status: Mapped[ModuleStatus] = mapped_column(
        SAEnum(ModuleStatus, name="module_status", native_enum=False, length=20),
        default=ModuleStatus.NOT_STARTED,
        nullable=False,
    )

    #: Набор «признак → есть/нет». Структура задаётся модулем сравнения.
    features: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    #: Условия предложения дословно: цены, сроки, гарантии, что бесплатно.
    #: Ради них сравнение и существует — по галочкам «есть форма» решение о
    #: том, чем отличаться от конкурента, принять нельзя.
    offer: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    #: Что это за сайт: конкурент, площадка объявлений, справочник, статья.
    #: Хранится рядом с признаками, потому что читается вместе с ними: у Авито
    #: всегда есть и форма, и цены, и отзывы, и без этой пометки сравнение с
    #: ним выглядит как разгромный проигрыш клиента.
    kind: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    error_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
