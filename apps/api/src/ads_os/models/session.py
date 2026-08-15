"""Сессия пользователя.

Сессии хранятся на сервере, а не в самоподписанном токене у клиента. Причина
одна и она решающая: сессию нужно уметь отозвать немедленно. Человек уволился,
ноутбук потеряли, доступ выдали по ошибке — во всех этих случаях нажатие
«отключить» должно действовать сразу, а не через сутки, когда истечёт срок
токена.

В базе лежит не сам токен, а его хеш. Утечка дампа базы не даёт возможности
войти чужой сессией — так же, как хранение хешей паролей не даёт узнать пароли.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base, Timestamps, UUIDPrimaryKey


class Session(UUIDPrimaryKey, Timestamps, Base):
    """Активный вход пользователя.

    Организация хранится вместе с пользователем: контекст запроса берётся
    отсюда целиком, и лишний запрос к пользователю на каждом обращении не
    нужен.
    """

    __tablename__ = "sessions"
    __table_args__ = (
        # Поиск идёт по хешу токена на каждом запросе — без индекса это стало бы
        # самым горячим местом системы.
        Index("ix_sessions_token_hash", "token_hash", unique=True),
        Index("ix_sessions_user_id", "user_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )

    #: SHA-256 от токена. Сам токен существует только в куке у пользователя.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: Проставляется при выходе или отключении участника. Отозванная сессия не
    #: удаляется: остаётся видно, что вход был и когда он закончился.
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    #: Откуда вошли. Нужно, чтобы человек узнал свою сессию в списке и заметил
    #: чужую. Полный User-Agent не хранится: это лишние данные без пользы.
    user_agent: Mapped[str | None] = mapped_column(String(200), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
