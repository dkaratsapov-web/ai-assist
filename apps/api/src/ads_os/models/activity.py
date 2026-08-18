"""Журнал действий (v0.3 §93).

Ради этого и заводились личные учётные записи. Пока вход был один на всех, на
вопрос «кто изменил бюджет» ответа не существовало в принципе. Теперь он есть —
но только если действия записываются.

Запись ведётся явными вызовами из обработчиков, а не автоматическим перехватом
запросов. Перехват записал бы всё подряд, включая чтение, и в журнале утонуло
бы то немногое, ради чего он существует: изменения, которые кто-то сделал
руками.

Записи не редактируются и не удаляются. Журнал, который можно поправить, не
является журналом.
"""

from __future__ import annotations

import uuid
from enum import StrEnum
from typing import Any

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base, OrganizationScoped, Timestamps, UUIDPrimaryKey


class ActivityAction(StrEnum):
    """Что именно произошло.

    Список закрытый: свободная строка со временем превратилась бы в набор
    похожих формулировок, по которому нельзя ни отфильтровать, ни посчитать.
    """

    PROJECT_CREATED = "project_created"
    PROJECT_UPDATED = "project_updated"
    PROJECT_DELETED = "project_deleted"

    ECONOMICS_UPDATED = "economics_updated"

    AUDIT_STARTED = "audit_started"
    ISSUE_DISMISSED = "issue_dismissed"
    ISSUE_RESTORED = "issue_restored"

    KEYWORDS_IMPORTED = "keywords_imported"
    KEYWORDS_CLEANED = "keywords_cleaned"
    MINUS_WORD_ADDED = "minus_word_added"
    MINUS_SET_SAVED = "minus_set_saved"
    MINUS_SET_APPLIED = "minus_set_applied"

    COMPETITOR_ADDED = "competitor_added"
    COMPETITOR_REMOVED = "competitor_removed"

    MEMBER_ADDED = "member_added"
    MEMBER_UPDATED = "member_updated"
    MEMBER_REMOVED = "member_removed"


class ActivityLog(UUIDPrimaryKey, Timestamps, OrganizationScoped, Base):
    """Одно действие человека."""

    __tablename__ = "activity_log"
    __table_args__ = (
        # Журнал читается лентой, от новых к старым, — это единственный частый
        # запрос к нему.
        Index("ix_activity_log_org_created", "organization_id", "created_at"),
    )

    #: Кто. Не удаляется вместе с пользователем: запись о действии должна
    #: пережить отключение автора, иначе журнал теряет смысл ровно тогда, когда
    #: становится нужен.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    #: Имя автора на момент действия. Хранится копией: человек может сменить
    #: имя или быть отключён, а в журнале должно остаться то, что было тогда.
    user_name: Mapped[str] = mapped_column(String(200), nullable=False)

    action: Mapped[ActivityAction] = mapped_column(
        SAEnum(ActivityAction, name="activity_action", native_enum=False, length=40),
        nullable=False,
    )

    #: К чему относится действие. Ссылка мягкая: проект могут удалить, а запись
    #: о его удалении обязана остаться.
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    #: Название объекта на момент действия — по той же причине, что и имя автора.
    subject: Mapped[str] = mapped_column(String(300), nullable=False)

    #: Что именно изменилось: пары «поле → было/стало». Пустой словарь означает
    #: действие без подробностей, а не потерянные данные.
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
