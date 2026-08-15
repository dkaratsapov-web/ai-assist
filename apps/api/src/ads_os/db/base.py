"""Базовые классы моделей и общие примеси.

Здесь собраны требования, которые v0.3 предъявляет ко всем сущностям сразу:
мягкое удаление (§61), версионирование (§62) и принадлежность организации (§93).
Вынесены в примеси, чтобы их нельзя было забыть в конкретной модели.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import ClassVar

from sqlalchemy import DateTime, ForeignKey, Integer, MetaData, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Явные имена ограничений: без них Alembic генерирует автоимена, и миграции
# становятся невоспроизводимыми между окружениями.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def utcnow() -> datetime:
    return datetime.now(UTC)


class UUIDPrimaryKey:
    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )


class Timestamps:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class SoftDelete:
    """Мягкое удаление (v0.3 §61).

    Важно: мягкое удаление не заменяет фактическое удаление по истечении срока
    хранения (v0.3 §110) — это отдельный процесс, а не альтернатива.
    """

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


class Versioned:
    """Оптимистичная блокировка (v0.3 §62, v0.4 §100).

    Перед исполнением действия состояние сущности перечитывается, и если версия
    изменилась — действие отклоняется. Это защита от выполнения согласования,
    подготовленного на устаревших данных.
    """

    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Переопределяется в конкретной модели.
    __mapper_args__: ClassVar[dict[str, object]] = {"version_id_col": None}


class OrganizationScoped:
    """Принадлежность организации.

    Обязательна для всех данных арендатора (v0.3 §93). Запросы к таким моделям
    идут только через репозиторий, который подставляет фильтр автоматически —
    полагаться на дисциплину вызывающего кода здесь нельзя.
    """

    organization_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
