"""Результат аудита сайта."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base, OrganizationScoped, Timestamps, UUIDPrimaryKey


class ModuleStatus(StrEnum):
    """Состояние работы модуля (v0.3 §5).

    Общее для всех долгих операций: аудита, сбора семантики, анализа
    конкурентов. Интерфейс показывает их одинаково, поэтому и в базе они
    называются одинаково.
    """

    NOT_STARTED = "not_started"
    QUEUED = "queued"
    RUNNING = "running"
    NEEDS_REVIEW = "needs_review"
    COMPLETED = "completed"
    FAILED = "failed"


class SiteAudit(UUIDPrimaryKey, Timestamps, OrganizationScoped, Base):
    """Один запуск аудита.

    История сохраняется целиком, а не перезаписывается: нужно видеть, что
    менялось на сайте между запусками (v0.3 §62). Текущим считается последний
    завершённый.
    """

    __tablename__ = "site_audits"
    __table_args__ = (
        # Последний аудит проекта запрашивается на каждом открытии экрана.
        Index("ix_site_audits_project_created", "project_id", "created_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )

    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    status: Mapped[ModuleStatus] = mapped_column(
        SAEnum(ModuleStatus, name="module_status", native_enum=False, length=20),
        default=ModuleStatus.QUEUED,
        nullable=False,
    )

    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    verdict: Mapped[str | None] = mapped_column(String(32), nullable=True)

    #: Разбор по категориям и список находок. Структура задаётся модулем
    #: аудита, здесь она хранится как есть — переносить её в отдельные таблицы
    #: незачем: она читается целиком и не участвует в выборках.
    categories: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    issues: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)

    #: Признаки страницы в том же виде, в каком они хранятся у конкурентов.
    #: Нужны для сравнения: без них пришлось бы восстанавливать «есть форма» из
    #: текста находок, и любая правка формулировки молча ломала бы сравнение.
    features: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    #: Короткие фрагменты предложения со страницы: «Замер бесплатно», «Гарантия
    #: 5 лет». Из них собираются черновики объявлений. Сохраняются вместе с
    #: проверкой, а не вычитываются заново: страница меняется, а черновик должен
    #: соответствовать той версии, которую проверяли.
    selling_points: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)

    #: Заголовок страницы. Нужен, чтобы сопоставить группу фраз с подходящей
    #: посадочной: по адресу это делать нельзя — он часто на латинице, а фразы
    #: на русском.
    page_title: Mapped[str | None] = mapped_column(String(300), nullable=True)

    #: Внутренние разделы сайта: пары «подпись, адрес». Из них собираются
    #: быстрые ссылки объявлений.
    internal_links: Mapped[list[list[str]]] = mapped_column(
        JSONB, default=list, nullable=False
    )

    metrica_counter: Mapped[str | None] = mapped_column(String(20), nullable=True)
    final_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    #: Причина отказа простым языком. Наружу не уходит ни трассировка, ни текст
    #: исключения (v0.3 §137).
    error_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def is_finished(self) -> bool:
        return self.status in (ModuleStatus.COMPLETED, ModuleStatus.FAILED)


class IssueDismissal(UUIDPrimaryKey, Timestamps, OrganizationScoped, Base):
    """Замечание, отмеченное как неактуальное для этого проекта.

    Система знает, чего на странице нет. Она не знает, почему: «цен нет» — это
    и недоработка, и осознанная позиция компании, которая считает стоимость
    индивидуально. Отличить одно от другого может только человек, поэтому
    решение принимает он, а система его запоминает.

    Скрытие не меняет ни балл, ни вердикт. Балл — это измерение, а не
    договорённость: если бы его можно было поднять, отметив замечание
    неактуальным, он перестал бы что-либо значить, в том числе для клиента,
    которому этот балл показывают.

    Критические замечания скрывать нельзя вовсе — блокировка, которую можно
    спрятать, не является блокировкой. Это проверяется на уровне API.
    """

    __tablename__ = "issue_dismissals"
    __table_args__ = (
        # Одно решение на замечание в проекте: повторное скрытие того же
        # замечания — это то же самое решение, а не второе.
        Index("uq_issue_dismissal", "project_id", "issue_key", unique=True),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    #: Устойчивое имя проверки из IssueKey. Хранится строкой, а не ссылкой на
    #: перечисление: набор проверок меняется, и удалённая проверка не должна
    #: ломать чтение старых решений.
    issue_key: Mapped[str] = mapped_column(String(60), nullable=False)

    #: Почему сочли неактуальным. Не обязательно, но именно это читает второй
    #: специалист через полгода, когда сомневается в решении.
    reason: Mapped[str | None] = mapped_column(String(300), nullable=True)

    dismissed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    #: Имя копией — по той же причине, что и в журнале действий.
    dismissed_by_name: Mapped[str] = mapped_column(String(200), nullable=False)
