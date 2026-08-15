"""Конкуренты проекта и сравнение с ними."""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, status
from sqlalchemy import Select, select

from ...errors import AppError, ConflictError
from ...models import Competitor, Project, SiteAudit
from ...models.audit import ModuleStatus
from ...services.competitors import FeatureKey, Participant, compare
from ...tenancy.repository import TenantRepository
from ...worker.tasks.competitors import enqueue_competitor
from ..deps import SessionDep, TenantDep, WriteDep
from ..schemas import (
    ComparisonRead,
    CompetitorCreate,
    CompetitorList,
    CompetitorRead,
    FeatureRowRead,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["competitors"])

#: Больше конкурентов сравнивать бессмысленно: таблица перестаёт читаться, а
#: краулер начинает заметно нагружать чужие сайты.
MAX_COMPETITORS = 10


class ProjectRepository(TenantRepository[Project]):
    model = Project


class CompetitorRepository(TenantRepository[Competitor]):
    model = Competitor

    def scoped(self, *, include_deleted: bool = False) -> Select[tuple[Competitor]]:
        # Мягкого удаления у конкурента нет: он удаляется насовсем.
        return select(self.model).where(self.model.organization_id == self.ctx.organization_id)


class TooManyCompetitorsError(AppError):
    status_code = 422
    error_code = "too_many_competitors"
    message = f"К проекту можно добавить не больше {MAX_COMPETITORS} конкурентов"


class QueueUnavailableError(AppError):
    status_code = 503
    error_code = "queue_unavailable"
    message = "Фоновые задачи временно недоступны. Попробуйте позже"
    retryable = True


@router.get(
    "/{project_id}/competitors",
    response_model=CompetitorList,
    summary="Конкуренты проекта",
)
async def list_competitors(
    project_id: uuid.UUID, session: SessionDep, ctx: TenantDep
) -> CompetitorList:
    await ProjectRepository(session, ctx).get_or_404(project_id)
    items = await _load(session, ctx, project_id)
    return CompetitorList(items=[_to_read(c) for c in items], total=len(items))


@router.post(
    "/{project_id}/competitors",
    response_model=CompetitorRead,
    status_code=status.HTTP_201_CREATED,
    summary="Добавить конкурента",
)
async def add_competitor(
    project_id: uuid.UUID, payload: CompetitorCreate, session: SessionDep, ctx: WriteDep
) -> CompetitorRead:
    await ProjectRepository(session, ctx).get_or_404(project_id)

    existing = await _load(session, ctx, project_id)

    if len(existing) >= MAX_COMPETITORS:
        raise TooManyCompetitorsError()

    url = payload.url.strip()
    if any(c.url == url for c in existing):
        # Дубль не просто лишняя строка: признак начинает считаться за двоих и
        # искажает сравнение.
        raise ConflictError(details={"url": url})

    competitor = Competitor(
        project_id=project_id,
        url=url,
        title=(payload.title or "").strip() or None,
        status=ModuleStatus.QUEUED,
        features={},
    )
    repo = CompetitorRepository(session, ctx)
    await repo.add(competitor)
    await session.flush()

    # Постановка в очередь может изменить статус записи (если очередь лежит),
    # поэтому изменения фиксируются после неё, а не до.
    _enqueue(competitor)
    await session.flush()

    return _to_read(competitor)


@router.post(
    "/{project_id}/competitors/{competitor_id}/recheck",
    response_model=CompetitorRead,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Перепроверить конкурента",
)
async def recheck_competitor(
    project_id: uuid.UUID, competitor_id: uuid.UUID, session: SessionDep, ctx: WriteDep
) -> CompetitorRead:
    await ProjectRepository(session, ctx).get_or_404(project_id)
    competitor = await CompetitorRepository(session, ctx).get_or_404(competitor_id)

    previous_status = competitor.status
    competitor.status = ModuleStatus.QUEUED
    competitor.error_reason = None
    await session.flush()

    try:
        enqueue_competitor(competitor.id, competitor.url)
    except Exception as exc:
        # Статус возвращается на место: конкурент, вечно висящий «в очереди»,
        # в которой его нет, выглядит как поломка системы.
        competitor.status = previous_status
        await session.flush()
        logger.warning(
            "не удалось поставить конкурента в очередь",
            extra={"competitor_id": str(competitor_id), "error": type(exc).__name__},
        )
        raise QueueUnavailableError() from exc

    return _to_read(competitor)


@router.delete(
    "/{project_id}/competitors/{competitor_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить конкурента",
)
async def delete_competitor(
    project_id: uuid.UUID, competitor_id: uuid.UUID, session: SessionDep, ctx: WriteDep
) -> None:
    await ProjectRepository(session, ctx).get_or_404(project_id)
    competitor = await CompetitorRepository(session, ctx).get_or_404(competitor_id)
    await session.delete(competitor)
    await session.flush()


@router.get(
    "/{project_id}/comparison",
    response_model=ComparisonRead,
    summary="Сравнение с конкурентами",
)
async def get_comparison(
    project_id: uuid.UUID, session: SessionDep, ctx: TenantDep
) -> ComparisonRead:
    project = await ProjectRepository(session, ctx).get_or_404(project_id)

    audit = await _latest_completed_audit(session, ctx, project_id)
    competitors = [c for c in await _load(session, ctx, project_id) if c.features]

    # Аудит без признаков — это аудит, снятый до появления сравнения. Считать
    # его проверкой нельзя: колонка «у вас» была бы сплошным «нет».
    own_checked = audit is not None and bool(audit.features)

    mine = Participant(
        url=project.website_url or "",
        title=project.name,
        features=_features_from_audit(audit if own_checked else None),
    )
    rivals = tuple(
        Participant(url=c.url, title=c.title or c.url, features=_features(c.features))
        for c in competitors
    )

    result = compare(mine, rivals)

    return ComparisonRead(
        project_id=project_id,
        own_site_checked=own_checked,
        rivals_checked=len(rivals),
        summary=result.summary,
        rows=[
            FeatureRowRead(
                key=row.key,
                label=row.label,
                why=row.why,
                mine=row.mine,
                rivals_with=row.rivals_with,
                rivals_total=row.rivals_total,
                is_gap=row.is_gap,
                is_advantage=row.is_advantage,
            )
            for row in result.rows
        ],
    )


def _enqueue(competitor: Competitor) -> None:
    try:
        enqueue_competitor(competitor.id, competitor.url)
    except Exception as exc:
        # Конкурент остаётся добавленным: перепроверить его можно кнопкой, а
        # терять введённый адрес из-за недоступной очереди незачем.
        competitor.status = ModuleStatus.NOT_STARTED
        competitor.error_reason = "Проверка не запущена: фоновые задачи недоступны"
        logger.warning(
            "не удалось поставить конкурента в очередь",
            extra={"competitor_id": str(competitor.id), "error": type(exc).__name__},
        )


async def _load(
    session: SessionDep, ctx: TenantDep, project_id: uuid.UUID
) -> list[Competitor]:
    stmt = (
        select(Competitor)
        .where(Competitor.organization_id == ctx.organization_id)
        .where(Competitor.project_id == project_id)
        .order_by(Competitor.created_at)
    )
    return list((await session.execute(stmt)).scalars().all())


async def _latest_completed_audit(
    session: SessionDep, ctx: TenantDep, project_id: uuid.UUID
) -> SiteAudit | None:
    stmt = (
        select(SiteAudit)
        .where(SiteAudit.organization_id == ctx.organization_id)
        .where(SiteAudit.project_id == project_id)
        .where(SiteAudit.status == ModuleStatus.COMPLETED)
        .order_by(SiteAudit.created_at.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


def _features(raw: dict[str, object]) -> dict[FeatureKey, bool]:
    return {key: bool(raw.get(key.value, False)) for key in FeatureKey}


def _features_from_audit(audit: SiteAudit | None) -> dict[FeatureKey, bool]:
    """Признаки своего сайта. Берутся из аудита как есть."""
    if audit is None:
        return dict.fromkeys(FeatureKey, False)
    return _features(audit.features or {})


def _to_read(competitor: Competitor) -> CompetitorRead:
    return CompetitorRead(
        id=competitor.id,
        project_id=competitor.project_id,
        url=competitor.url,
        title=competitor.title,
        status=competitor.status,
        features={key: value for key, value in (competitor.features or {}).items()},
        error_reason=competitor.error_reason,
        checked_at=competitor.checked_at,
    )
