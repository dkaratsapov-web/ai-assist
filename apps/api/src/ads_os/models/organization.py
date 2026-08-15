"""Организация и её лимиты."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.base import Base, SoftDelete, Timestamps, UUIDPrimaryKey

if TYPE_CHECKING:
    from .project import Project
    from .user import User


class Organization(UUIDPrimaryKey, Timestamps, SoftDelete, Base):
    """Верхний уровень многоарендности (v0.3 §60).

    Сама организация не наследует OrganizationScoped: она и есть граница
    изоляции, а не объект внутри неё.
    """

    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)

    users: Mapped[list[User]] = relationship(back_populates="organization")
    projects: Mapped[list[Project]] = relationship(back_populates="organization")
    plan: Mapped[OrganizationPlan | None] = relationship(
        back_populates="organization", uselist=False
    )


class OrganizationPlan(UUIDPrimaryKey, Timestamps, Base):
    """Лимиты организации (v0.4 §13).

    Платёжная система в MVP не подключается, но учёт потребления и потолки нужны
    с первого дня — иначе их некуда будет добавить, когда биллинг появится.
    """

    __tablename__ = "organization_plans"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    max_projects: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    max_users: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    ai_usage_limit: Mapped[int] = mapped_column(Integer, default=100_000, nullable=False)
    crawler_pages_limit: Mapped[int] = mapped_column(Integer, default=5_000, nullable=False)
    semantic_requests_limit: Mapped[int] = mapped_column(Integer, default=10_000, nullable=False)
    report_limit: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    retention_days: Mapped[int] = mapped_column(Integer, default=395, nullable=False)

    # Автопилот выключен по умолчанию на уровне плана и отдельно на уровне
    # проекта: два независимых выключателя (v0.4 §10).
    autopilot_allowed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    organization: Mapped[Organization] = relationship(back_populates="plan")
