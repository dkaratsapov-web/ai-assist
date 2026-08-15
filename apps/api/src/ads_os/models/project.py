"""Проект — корень Project Data Core (v0.3 §3)."""

from __future__ import annotations

import uuid
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING, ClassVar

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.base import Base, OrganizationScoped, SoftDelete, Timestamps, UUIDPrimaryKey

if TYPE_CHECKING:
    from .organization import Organization


class ProjectStatus(StrEnum):
    """Технический статус проекта.

    Намеренно не совпадает один в один с десятишаговым пользовательским
    жизненным циклом (v0.4 §3): интерфейс показывает этап работы, база хранит
    состояние обработки, и смешивать их не нужно.
    """

    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"
    ERROR = "error"


class MainConversion(StrEnum):
    """Основная целевая конверсия проекта (v0.3 §13)."""

    LEAD = "lead"
    CALL = "call"
    MESSAGE = "message"
    ORDER = "order"
    PURCHASE = "purchase"


class Project(UUIDPrimaryKey, Timestamps, SoftDelete, OrganizationScoped, Base):
    __tablename__ = "projects"
    # SQLAlchemy объявляет __mapper_args__ переменной экземпляра, но читает его
    # с класса. Аннотация ClassVar здесь корректна, а замечание mypy — следствие
    # его собственного описания базового класса.
    __mapper_args__: ClassVar[dict[str, object]] = {  # type: ignore[misc]
        "version_id_col": None
    }

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    website_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    primary_region: Mapped[str | None] = mapped_column(String(120), nullable=True)

    status: Mapped[ProjectStatus] = mapped_column(
        SAEnum(ProjectStatus, name="project_status", native_enum=False, length=20),
        default=ProjectStatus.DRAFT,
        nullable=False,
    )

    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    organization: Mapped[Organization] = relationship(back_populates="projects")
    economics: Mapped[ProjectEconomics | None] = relationship(
        back_populates="project", uselist=False, cascade="all, delete-orphan"
    )


class ProjectEconomics(UUIDPrimaryKey, Timestamps, OrganizationScoped, Base):
    """Экономика проекта (v0.3 §19, v0.4 §5).

    Разделение полей на обязательные и рекомендованные — не формальность.
    Без обязательных нельзя вести проект вообще; без рекомендованных проект
    ведётся, но оптимизация по продажам и марже недоступна, и система обязана
    честно это показывать, а не подставлять правдоподобные числа.

    Все денежные величины хранятся в Numeric: расчёты маржи и CAC на float дают
    накопленную ошибку, а речь идёт о деньгах клиента.
    """

    __tablename__ = "project_economics"

    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    # ── Обязательный ввод (v0.4 §5) ────────────────────────────────────────
    monthly_budget: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    average_order_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    #: Замена среднему чеку там, где чека нет: ожидаемая ценность клиента.
    expected_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    main_conversion: Mapped[MainConversion | None] = mapped_column(
        SAEnum(MainConversion, name="main_conversion", native_enum=False, length=20),
        nullable=True,
    )

    # ── Рекомендованный ввод ───────────────────────────────────────────────
    margin_percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    lead_to_sale_rate: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)
    target_cac: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    target_cpl: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)

    #: Какая доля валовой прибыли готова уходить на привлечение. Нужна, чтобы
    #: вывести целевой CAC, когда пользователь его не задал.
    #: Ожидаемая цена клика и конверсия посадочной страницы.
    #:
    #: Без них ёмкость бюджета считалась тавтологично: «бюджет ÷ целевая цена
    #: лида» отвечает на вопрос, на сколько заявок хватит денег, если цена
    #: окажется целевой, — а не сколько заявок будет. На старте реальная цена
    #: почти всегда выше целевой, и разница между этими двумя утверждениями
    #: определяет, окупится кампания или нет.
    expected_cpc: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    site_conversion_rate: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)

    target_marketing_share: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), nullable=True)

    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    project: Mapped[Project] = relationship(back_populates="economics")
