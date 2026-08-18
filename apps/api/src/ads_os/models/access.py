"""Доступ участника к отдельным проектам.

Раньше участник видел все проекты организации. Для агентства, где один
специалист ведёт трёх клиентов, а второй — других трёх, это неверно: чужие
бюджеты, чужие ставки и чужие заявки видеть незачем. Тем более это неверно для
самого клиента, которому дают посмотреть на свой проект.

Устроено списком разрешений, а не запретов. Запись здесь означает «этому
человеку открыт этот проект»; всё, чего в списке нет, для него не существует —
не «видно, но нельзя открыть», а именно не существует, как чужая организация.

У кого список не спрашивают. У владельца: он отвечает за организацию целиком, и
проект, скрытый от него, был бы проектом, за который никто не отвечает. И у
участников, отмеченных как видящие все проекты, — это прежнее поведение, и оно
остаётся значением по умолчанию, чтобы появление этой таблицы никого ничего не
лишило.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base, OrganizationScoped, Timestamps, UUIDPrimaryKey


class ProjectAccess(UUIDPrimaryKey, Timestamps, OrganizationScoped, Base):
    """Один проект, открытый одному участнику."""

    __tablename__ = "project_access"
    __table_args__ = (
        # Повторная выдача того же доступа не должна плодить записи: иначе
        # отзыв одной строкой оставил бы человека внутри.
        UniqueConstraint("user_id", "project_id", name="uq_project_access_user_project"),
        # Список читается на каждом запросе участника — по нему и индекс.
        Index("ix_project_access_user", "user_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )

    #: Кто открыл доступ. Нужно журналу: «почему этот человек видит проект» —
    #: вопрос, который задают через полгода, и отвечать на него надо не догадкой.
    granted_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
