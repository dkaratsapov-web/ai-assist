"""Пользователь."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, String, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.base import Base, OrganizationScoped, SoftDelete, Timestamps, UUIDPrimaryKey
from ..tenancy.context import Role

if TYPE_CHECKING:
    from .organization import Organization


class User(UUIDPrimaryKey, Timestamps, SoftDelete, OrganizationScoped, Base):
    __tablename__ = "users"
    __table_args__ = (
        # Почта уникальна внутри организации, а не глобально: один человек может
        # работать в нескольких организациях как разные пользователи.
        UniqueConstraint("organization_id", "email", name="organization_id_email"),
    )

    email: Mapped[str] = mapped_column(String(320), nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[Role] = mapped_column(
        SAEnum(Role, name="user_role", native_enum=False, length=20), nullable=False
    )

    # Пароль здесь не хранится: аутентификация появится отдельным срезом вместе
    # с MFA (v0.3 §91). Поле-заглушка не заводится намеренно, чтобы не возникло
    # соблазна положить в него что-нибудь временное.

    #: Идентификатор в Яндекс ID. Заполняется при первом входе.
    #:
    #: После этого сопоставление идёт по нему, а не по почте: почту в аккаунте
    #: можно сменить, и привязка по ней однажды тихо перестанет работать.
    yandex_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    #: Включена ли двухфакторная аутентификация. Вход идёт через Яндекс ID,
    #: поэтому значение приходит оттуда и нами не устанавливается (v0.3 §91).
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    #: Видит ли участник все проекты организации.
    #:
    #: По умолчанию да — это прежнее поведение, и появление списка доступов
    #: никого ничего не лишает. Снимается, когда владелец открывает человеку
    #: конкретные проекты: с этого момента список решает всё, и проект, которого
    #: в нём нет, для человека не существует. Владельца это не касается — он
    #: отвечает за организацию целиком.
    all_projects: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    #: Отключённый участник не может войти, а его сессии отзываются. Удаление
    #: не используется: история действий должна оставаться связанной с автором.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    organization: Mapped[Organization] = relationship(back_populates="users")
