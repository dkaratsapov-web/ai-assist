"""Наборы минус-слов, общие для всех проектов организации.

Специалист накапливает такие списки годами: «вакансии, работа, резюме» нужны
почти везде, «б/у, авито, самому» — в услугах, «реферат, курсовая» — в обучении.
Переписывать их руками в каждый новый проект — самая обидная потеря времени:
работа сделана давно, но результат никуда не сохранён.

Набор принадлежит организации, а не проекту. В этом весь смысл: если бы он жил
внутри проекта, его пришлось бы копировать — то есть делать то же самое, только
через интерфейс.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base, OrganizationScoped, Timestamps, UUIDPrimaryKey


class MinusWordSet(UUIDPrimaryKey, Timestamps, OrganizationScoped, Base):
    """Именованный список минус-слов."""

    __tablename__ = "minus_word_sets"
    __table_args__ = (Index("uq_minus_word_set_name", "organization_id", "name", unique=True),)

    name: Mapped[str] = mapped_column(String(120), nullable=False)

    #: Слова списком, а не отдельными строками таблицы. Набор всегда читается и
    #: применяется целиком, отдельное слово в нём не является самостоятельной
    #: сущностью — и таблица на сотню строк ради этого только мешала бы.
    words: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)

    #: Кто создал. Имя не копируется: набор живёт в организации, и вопрос «кто
    #: его завёл» решается журналом действий, а не полем здесь.
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
