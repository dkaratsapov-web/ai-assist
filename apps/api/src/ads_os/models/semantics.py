"""Семантическое ядро проекта: фразы и минус-слова."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base, OrganizationScoped, Timestamps, UUIDPrimaryKey
from ..services.semantics import Intent


class Keyword(UUIDPrimaryKey, Timestamps, OrganizationScoped, Base):
    """Одна поисковая фраза."""

    __tablename__ = "keywords"
    __table_args__ = (
        # Одна фраза в проекте существует один раз. Повторный импорт того же
        # списка обновляет её, а не создаёт вторую копию: иначе ядро росло бы
        # с каждой загрузкой, а частотности расходились бы между дублями.
        Index("uq_keyword_phrase", "project_id", "phrase", unique=True),
        Index("ix_keyword_project_intent", "project_id", "intent"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )

    phrase: Mapped[str] = mapped_column(String(400), nullable=False)
    #: Частотность из выгрузки. None означает «не измеряли», а не «ноль».
    frequency: Mapped[int | None] = mapped_column(Integer, nullable=True)

    intent: Mapped[Intent] = mapped_column(
        SAEnum(Intent, name="keyword_intent", native_enum=False, length=20), nullable=False
    )
    #: Слово, из-за которого фраза отнесена к этому типу. Пусто, если признаков
    #: не нашлось и сработало правило по умолчанию.
    trigger: Mapped[str | None] = mapped_column(String(60), nullable=True)

    #: Решение принято человеком, а не словарём. Повторный разбор такие фразы
    #: не трогает — иначе правка терялась бы при каждом импорте, и доверие к
    #: ручным решениям исчезло бы вместе с ней.
    is_manual: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    #: Название группы. Хранится строкой, а не ссылкой: группы пересчитываются
    #: целиком, и связь на удаляемую запись только мешала бы.
    cluster_name: Mapped[str | None] = mapped_column(String(400), nullable=True)

    #: Группу назначил человек, а не расчёт.
    #:
    #: До появления этого признака группы пересчитывались при каждом сборе и
    #: правку не переживали: специалист переносил фразу, а следующая загрузка
    #: возвращала её обратно. Редактирование, которое отменяется само, хуже
    #: отсутствующего — на него тратят время, а результата нет.
    cluster_manual: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class KeywordBrief(UUIDPrimaryKey, Timestamps, OrganizationScoped, Base):
    """Ответы клиента, из которых строятся маски для Вордстата.

    Хранится, а не спрашивается каждый раз: бриф заполняют один раз в начале
    проекта, а возвращаются к маскам по нескольку раз — собрать хвост, добавить
    новое направление, пересобрать после смены услуг.
    """

    __tablename__ = "keyword_briefs"
    __table_args__ = (Index("uq_keyword_brief_project", "project_id", unique=True),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )

    #: Что продаём.
    sells: Mapped[str] = mapped_column(Text, default="", nullable=False)
    #: Как это называют иначе. Чужие слова важнее своих: человек ищет теми, к
    #: которым привык, а не теми, что в прайсе клиента.
    synonyms: Mapped[str] = mapped_column(Text, default="", nullable=False)
    #: Чего не делаем. Единственная часть брифа, которую нельзя угадать.
    excludes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    #: Города, если они не совпадают с регионом проекта.
    cities: Mapped[str] = mapped_column(Text, default="", nullable=False)

    #: Ответы на вопросы, на которые сайт не отвечает: средний чек, маржа,
    #: что клиент не делает, куда попадают заявки. Лежат здесь же, потому что
    #: это та же анкета проекта — просто вторая её половина.
    #:
    #: Свободным словарём, а не столбцами: набор вопросов зависит от ниши и
    #: от того, что не удалось прочитать с сайта, то есть меняется вместе с
    #: кодом. Столбец на каждый вопрос означал бы миграцию на каждый вопрос,
    #: а старые ответы на удалённые вопросы всё равно надо сохранять: они
    #: писались про этого клиента и остаются правдой о нём.
    answers: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)


class MinusWord(UUIDPrimaryKey, Timestamps, OrganizationScoped, Base):
    """Слово, по которому показов быть не должно."""

    __tablename__ = "minus_words"
    __table_args__ = (Index("uq_minus_word", "project_id", "word", unique=True),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    word: Mapped[str] = mapped_column(String(60), nullable=False)
