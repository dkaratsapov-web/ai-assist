"""Репозиторий с автоматической изоляцией арендаторов.

Ключевое требование v0.3 §93: фильтр по организации применяется слоем
репозитория, а не вызывающим кодом. Полагаться на то, что каждый разработчик
не забудет добавить `where(organization_id == ...)`, нельзя — цена одной
забытой проверки это утечка данных чужого клиента (SEC-001, SEC-015).

Поэтому здесь нет метода, возвращающего незаполненный запрос. Системный доступ
поверх границ арендатора вынесен в отдельный класс с говорящим именем, чтобы
такой вызов было видно на ревью.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from typing import Any, Generic, TypeVar

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.base import Base
from ..errors import ConflictError, NotFoundError
from .context import TenantContext, current_context

logger = logging.getLogger(__name__)

ModelT = TypeVar("ModelT", bound=Base)


class TenantRepository(Generic[ModelT]):
    """Базовый репозиторий для данных, принадлежащих организации."""

    model: type[ModelT]

    def __init__(self, session: AsyncSession, ctx: TenantContext | None = None) -> None:
        self.session = session
        self._ctx = ctx

    @property
    def ctx(self) -> TenantContext:
        return self._ctx or current_context()

    # ── Построение запросов ────────────────────────────────────────────────

    def scoped(self, *, include_deleted: bool = False) -> Select[tuple[ModelT]]:
        """Запрос, уже ограниченный текущей организацией.

        Единственная точка входа для чтения. Мягко удалённые записи по умолчанию
        не видны: удалённый проект не должен появляться в списках (v0.3 §61).
        """
        stmt = select(self.model).where(
            self.model.organization_id == self.ctx.organization_id  # type: ignore[attr-defined]
        )

        # Второй рубеж изоляции — внутри организации. Участнику, которому
        # открыли отдельные проекты, чужие проекты не просто закрыты: их для
        # него не существует, как не существует чужой организации. Фильтр
        # стоит здесь по той же причине, что и первый: полагаться на то, что
        # каждый запрос где-то в коде не забудет его добавить, нельзя.
        if (column := self._project_column()) is not None:
            stmt = stmt.where(column.in_(self.ctx.allowed_projects or ()))

        if not include_deleted:
            stmt = stmt.where(self.model.deleted_at.is_(None))  # type: ignore[attr-defined]
        return stmt

    def _project_column(self) -> Any | None:
        """По какому столбцу сужать выборку до открытых проектов.

        Возвращает None, когда сужать не нужно вовсе: участник видит все
        проекты, либо у сущности нет привязки к проекту. Второе — не дыра:
        участники, справочники и настройки организации к проектам не относятся,
        и прятать их по признаку проекта не от чего.
        """
        if self.ctx.allowed_projects is None:
            return None

        if (column := getattr(self.model, "project_id", None)) is not None:
            return column

        # Сам проект своего project_id не имеет — у него это первичный ключ.
        if getattr(self.model, "__tablename__", "") == "projects":
            return self.model.id  # type: ignore[attr-defined]

        return None

    # ── Чтение ─────────────────────────────────────────────────────────────

    async def get(self, entity_id: uuid.UUID, *, include_deleted: bool = False) -> ModelT | None:
        stmt = self.scoped(include_deleted=include_deleted).where(
            self.model.id == entity_id  # type: ignore[attr-defined]
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_or_404(self, entity_id: uuid.UUID) -> ModelT:
        """Возвращает объект либо ошибку «не найдено».

        Чужой объект даёт ровно тот же ответ, что и несуществующий: разница
        между 403 и 404 позволила бы перебором выяснять, какие идентификаторы
        существуют у других организаций (SEC-001).
        """
        entity = await self.get(entity_id)
        if entity is None:
            raise NotFoundError()
        return entity

    async def list(
        self, *, limit: int = 50, offset: int = 0, include_deleted: bool = False
    ) -> Sequence[ModelT]:
        stmt = self.scoped(include_deleted=include_deleted).limit(limit).offset(offset)
        return (await self.session.execute(stmt)).scalars().all()

    async def count(self, *, include_deleted: bool = False) -> int:
        from sqlalchemy import func

        stmt = self.scoped(include_deleted=include_deleted).with_only_columns(
            func.count()
        ).order_by(None)
        return (await self.session.execute(stmt)).scalar_one()

    # ── Запись ─────────────────────────────────────────────────────────────

    async def add(self, entity: ModelT) -> ModelT:
        """Добавляет объект, проставляя организацию из контекста.

        Организацию нельзя передать снаружи: идентификатор из запроса клиента не
        является основанием для авторизации (v0.3 §93).
        """
        current = getattr(entity, "organization_id", None)
        if current is not None and current != self.ctx.organization_id:
            logger.error(
                "попытка создать объект в чужой организации",
                extra={
                    "model": self.model.__name__,
                    "context_org": str(self.ctx.organization_id),
                },
            )
            raise NotFoundError()

        entity.organization_id = self.ctx.organization_id  # type: ignore[attr-defined]
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def soft_delete(self, entity_id: uuid.UUID) -> ModelT:
        from ..db.base import utcnow

        entity = await self.get_or_404(entity_id)
        entity.deleted_at = utcnow()  # type: ignore[attr-defined]
        await self.session.flush()
        return entity

    async def expect_version(self, entity: ModelT, expected: int) -> None:
        """Проверяет, что состояние не изменилось с момента подготовки действия.

        Согласование, выданное на одних данных, не должно исполняться на других
        (v0.4 §100). Проверка выполняется непосредственно перед записью.
        """
        actual = getattr(entity, "version", None)
        if actual is not None and actual != expected:
            raise ConflictError(
                details={"expected_version": expected, "actual_version": actual}
            )


class SystemRepository(Generic[ModelT]):
    """Доступ поверх границ арендатора — только для системных задач.

    Существует для миграций данных, агрегации обезличенных бенчмарков и
    обслуживания. Каждый вызов пишется в лог: такой доступ должен быть заметен.
    """

    model: type[ModelT]

    def __init__(self, session: AsyncSession, reason: str) -> None:
        self.session = session
        self.reason = reason
        logger.warning(
            "доступ вне границ арендатора",
            extra={"model": self.model.__name__, "reason": reason},
        )

    def unscoped(self) -> Select[tuple[ModelT]]:
        return select(self.model)

    async def execute(self, stmt: Select[Any]) -> Any:
        return await self.session.execute(stmt)
