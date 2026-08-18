"""Сбор частотностей по маскам.

Отдельная запись, а не поле у проекта, потому что сбор — это не состояние, а
происходящее: он начинается, идёт часами, прерывается кончившейся квотой и
продолжается сам. Всё это нужно видеть, а не узнавать по факту.

Сто запросов в час на весь сервис — то ограничение, из которого выросла эта
таблица. Сбор нельзя сделать кнопкой, за которой человек ждёт ответа: десять
масок могут занять минуты, а могут упереться в лимит и растянуться на час.
Поэтому собранное сохраняется по мере поступления, а не в конце, и каждая
маска отмечается отдельно — иначе после перерыва пришлось бы начинать сначала
и тратить квоту на уже собранное.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base, OrganizationScoped, Timestamps, UUIDPrimaryKey
from .audit import ModuleStatus


class KeywordCollection(UUIDPrimaryKey, Timestamps, OrganizationScoped, Base):
    """Один запуск сбора частотностей."""

    __tablename__ = "keyword_collections"
    __table_args__ = (
        # Последний сбор проекта читается при каждом открытии экрана семантики.
        Index("ix_keyword_collections_project_created", "project_id", "created_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )

    status: Mapped[ModuleStatus] = mapped_column(
        SAEnum(ModuleStatus, name="module_status", native_enum=False, length=20),
        default=ModuleStatus.QUEUED,
        nullable=False,
    )

    #: Маски и что с каждой стало: `[{"query": ..., "state": "done",
    #: "found": 240, "total": 48200, "reason": ""}]`.
    #:
    #: Списком в одном поле, а не отдельной таблицей: он читается и пишется
    #: целиком, по нему не делают выборок, и живёт он ровно столько же, сколько
    #: сам сбор. Отдельная таблица дала бы соединение на каждом чтении и ничего
    #: взамен.
    masks: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)

    #: Сколько фраз добавлено и сколько обновлено. Разные числа: пересбор по
    #: тем же маскам почти целиком состоит из обновлений, и показать его как
    #: «добавлено 0» значило бы сказать, что сбор ничего не дал.
    added: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    #: Сколько запросов к площадке потрачено. По нему видно цену сбора и
    #: становится понятно, почему следующий упёрся в лимит.
    requests: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    #: Когда сбор продолжится, если он остановлен кончившейся квотой. Пусто,
    #: пока ждать нечего.
    resumes_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    #: Причина отказа простым языком. Ни трассировки, ни текста исключения
    #: наружу не уходит (v0.3 §137).
    error_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def is_finished(self) -> bool:
        return self.status in (ModuleStatus.COMPLETED, ModuleStatus.FAILED)
