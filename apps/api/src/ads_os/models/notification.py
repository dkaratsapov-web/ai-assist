"""Уведомления: то, что система сообщает сама.

Без них продукт остаётся инструментом, который надо не забыть открыть. Клиент
снял форму с посадочной в четверг, специалист заметил это в понедельник — за
выходные бюджет ушёл на страницу, с которой нельзя оставить заявку. Заметить
такое вовремя может только тот, кто смотрит постоянно, и это не человек.

Уведомление создаётся, только когда состояние изменилось к худшему. «Всё
по-прежнему хорошо» уведомлением не является: список, куда каждый день падает
отчёт об отсутствии проблем, перестают читать через неделю, и вместе с ним
перестают замечать настоящие.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base, OrganizationScoped, Timestamps, UUIDPrimaryKey


class NotificationKind(StrEnum):
    """О чём уведомление.

    Закрытый список: свободная строка со временем превратилась бы в набор
    похожих формулировок, по которому нельзя ни отфильтровать, ни настроить
    правила доставки.
    """

    #: На сайте появились замечания, которых не было. Обычно значит, что
    #: клиент что-то поменял и сломал.
    SITE_BROKEN = "site_broken"
    #: Оценка сайта заметно упала, хотя блокирующих замечаний не появилось.
    SITE_DEGRADED = "site_degraded"
    #: Проверка не смогла открыть сайт. Это либо сайт лежит, либо адрес сменили.
    SITE_UNREACHABLE = "site_unreachable"


class NotificationLevel(StrEnum):
    """Насколько срочно. Совпадает со словарём статусов интерфейса."""

    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


class Notification(UUIDPrimaryKey, Timestamps, OrganizationScoped, Base):
    """Одно сообщение системы."""

    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notification_org_created", "organization_id", "created_at"),
        # Одно и то же событие не создаётся дважды: повторная проверка,
        # нашедшая ту же поломку, не должна засыпать список копиями. Ключ
        # уникален в пределах проекта, пока уведомление не прочитано.
        Index("ix_notification_dedup", "project_id", "dedup_key", "is_read"),
    )

    project_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )
    #: Название проекта копией — уведомление должно оставаться читаемым и
    #: после удаления проекта.
    project_name: Mapped[str] = mapped_column(String(200), nullable=False)

    kind: Mapped[NotificationKind] = mapped_column(
        SAEnum(NotificationKind, name="notification_kind", native_enum=False, length=40),
        nullable=False,
    )
    level: Mapped[NotificationLevel] = mapped_column(
        SAEnum(NotificationLevel, name="notification_level", native_enum=False, length=20),
        nullable=False,
    )

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    #: Что именно случилось и что с этим делать. Уведомление без второго —
    #: это тревога без выхода, и от неё больше вреда, чем пользы.
    body: Mapped[str] = mapped_column(String(600), nullable=False)

    #: Признак повторности события. Формируется из вида и сути изменения.
    dedup_key: Mapped[str] = mapped_column(String(200), nullable=False)

    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
