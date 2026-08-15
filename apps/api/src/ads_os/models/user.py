"""Пользователь."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, String, UniqueConstraint
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

    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    organization: Mapped[Organization] = relationship(back_populates="users")
