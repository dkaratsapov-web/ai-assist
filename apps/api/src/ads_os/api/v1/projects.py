"""Проекты и их экономика."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status

from ...errors import ConflictError
from ...models import Project, ProjectEconomics
from ...services.economics import (
    EconomicsInput,
    EconomicsSummary,
    Metric,
    evaluate,
)
from ...tenancy.repository import TenantRepository
from ..deps import SessionDep, TenantDep, WriteDep
from ..schemas import (
    EconomicsResponse,
    EconomicsSummaryRead,
    EconomicsUpdate,
    MetricRead,
    ProjectCreate,
    ProjectList,
    ProjectRead,
)

router = APIRouter(prefix="/projects", tags=["projects"])


class ProjectRepository(TenantRepository[Project]):
    model = Project


class EconomicsRepository(TenantRepository[ProjectEconomics]):
    model = ProjectEconomics

    def scoped(self, *, include_deleted: bool = False):  # type: ignore[override]
        # У экономики нет мягкого удаления: она живёт и умирает вместе с
        # проектом, а не отдельно от него.
        from sqlalchemy import select

        return select(self.model).where(
            self.model.organization_id == self.ctx.organization_id
        )


@router.get("", response_model=ProjectList, summary="Список проектов")
async def list_projects(
    session: SessionDep,
    ctx: TenantDep,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> ProjectList:
    repo = ProjectRepository(session, ctx)
    items = await repo.list(limit=limit, offset=offset)
    return ProjectList(
        items=[ProjectRead.model_validate(p) for p in items],
        total=await repo.count(),
    )


@router.post(
    "",
    response_model=ProjectRead,
    status_code=status.HTTP_201_CREATED,
    summary="Создать проект",
)
async def create_project(
    payload: ProjectCreate, session: SessionDep, ctx: WriteDep
) -> ProjectRead:
    repo = ProjectRepository(session, ctx)
    project = await repo.add(
        Project(
            name=payload.name,
            website_url=payload.website_url,
            primary_region=payload.primary_region,
            created_by_id=ctx.user_id,
        )
    )
    return ProjectRead.model_validate(project)


@router.get("/{project_id}", response_model=ProjectRead, summary="Проект")
async def get_project(
    project_id: uuid.UUID, session: SessionDep, ctx: TenantDep
) -> ProjectRead:
    repo = ProjectRepository(session, ctx)
    return ProjectRead.model_validate(await repo.get_or_404(project_id))


@router.get(
    "/{project_id}/economics",
    response_model=EconomicsResponse,
    summary="Экономика проекта и производные метрики",
)
async def get_economics(
    project_id: uuid.UUID, session: SessionDep, ctx: TenantDep
) -> EconomicsResponse:
    repo = ProjectRepository(session, ctx)
    await repo.get_or_404(project_id)

    economics = await _load_economics(session, ctx, project_id)
    summary = evaluate(_to_input(economics))

    return EconomicsResponse(
        project_id=project_id,
        input=economics,  # type: ignore[arg-type]
        summary=_to_summary(summary),
    )


@router.put(
    "/{project_id}/economics",
    response_model=EconomicsResponse,
    summary="Сохранить экономику проекта",
)
async def update_economics(
    project_id: uuid.UUID,
    payload: EconomicsUpdate,
    session: SessionDep,
    ctx: WriteDep,
) -> EconomicsResponse:
    project_repo = ProjectRepository(session, ctx)
    await project_repo.get_or_404(project_id)

    economics = await _load_economics(session, ctx, project_id)

    is_new = economics is None

    if economics is None:
        # Версия проставляется явно: значение по умолчанию применяется только
        # при записи в базу, а увеличить её нужно до этого момента.
        economics = ProjectEconomics(project_id=project_id, version=1)
        economics.organization_id = ctx.organization_id
        session.add(economics)
    elif payload.expected_version is not None and economics.version != payload.expected_version:
        # Экономика меняет пороги всех последующих рекомендаций, поэтому запись
        # поверх чужого изменения недопустима (v0.4 §100).
        raise ConflictError(
            details={
                "expected_version": payload.expected_version,
                "actual_version": economics.version,
            }
        )

    updates = payload.model_dump(exclude={"expected_version"}, exclude_unset=True)
    for key, value in updates.items():
        setattr(economics, key, value)

    # Первая запись создаётся сразу первой версией; счётчик растёт только при
    # последующих изменениях, иначе номера версий начинались бы с двойки.
    if not is_new:
        economics.version += 1

    await session.flush()

    summary = evaluate(_to_input(economics))
    return EconomicsResponse(
        project_id=project_id,
        input=economics,  # type: ignore[arg-type]
        summary=_to_summary(summary),
    )


async def _load_economics(
    session: SessionDep, ctx: TenantDep, project_id: uuid.UUID
) -> ProjectEconomics | None:
    repo = EconomicsRepository(session, ctx)
    stmt = repo.scoped().where(ProjectEconomics.project_id == project_id)
    return (await session.execute(stmt)).scalar_one_or_none()


def _to_input(economics: ProjectEconomics | None) -> EconomicsInput:
    if economics is None:
        return EconomicsInput()
    return EconomicsInput(
        monthly_budget=economics.monthly_budget,
        average_order_value=economics.average_order_value,
        expected_value=economics.expected_value,
        main_conversion=economics.main_conversion.value if economics.main_conversion else None,
        margin_percent=economics.margin_percent,
        lead_to_sale_rate=economics.lead_to_sale_rate,
        target_cac=economics.target_cac,
        target_cpl=economics.target_cpl,
        target_marketing_share=economics.target_marketing_share,
    )


def _metric(metric: Metric) -> MetricRead:
    return MetricRead(
        value=metric.value, availability=metric.availability, reason=metric.reason
    )


def _to_summary(summary: EconomicsSummary) -> EconomicsSummaryRead:
    return EconomicsSummaryRead(
        mode=summary.mode,
        can_optimize_by_sales=summary.can_optimize_by_sales,
        cta=summary.cta,
        missing_required=summary.missing_required,
        missing_recommended=summary.missing_recommended,
        gross_profit_per_sale=_metric(summary.gross_profit_per_sale),
        break_even_cac=_metric(summary.break_even_cac),
        break_even_cpl=_metric(summary.break_even_cpl),
        break_even_roas=_metric(summary.break_even_roas),
        target_cac=_metric(summary.target_cac),
        target_cpl=_metric(summary.target_cpl),
        target_roas=_metric(summary.target_roas),
        monthly_leads_capacity=_metric(summary.monthly_leads_capacity),
        monthly_sales_capacity=_metric(summary.monthly_sales_capacity),
        projected_revenue=_metric(summary.projected_revenue),
        projected_gross_profit=_metric(summary.projected_gross_profit),
    )

