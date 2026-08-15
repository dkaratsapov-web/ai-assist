"""Проекты и их экономика."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status
from sqlalchemy import Select, func, select

from ...errors import ConflictError
from ...models import Competitor, Project, ProjectEconomics, SiteAudit
from ...models.audit import ModuleStatus
from ...services.economics import (
    EconomicsInput,
    EconomicsSummary,
    Metric,
    evaluate,
)
from ...services.progress import ProgressInput
from ...services.progress import evaluate as evaluate_progress
from ...tenancy.repository import TenantRepository
from ..deps import SessionDep, TenantDep, WriteDep
from ..schemas import (
    EconomicsResponse,
    EconomicsSummaryRead,
    EconomicsUpdate,
    MetricRead,
    ProgressRead,
    ProjectCreate,
    ProjectList,
    ProjectRead,
    ProjectUpdate,
    StepRead,
)

router = APIRouter(prefix="/projects", tags=["projects"])


class ProjectRepository(TenantRepository[Project]):
    model = Project


class EconomicsRepository(TenantRepository[ProjectEconomics]):
    model = ProjectEconomics

    def scoped(self, *, include_deleted: bool = False) -> Select[tuple[ProjectEconomics]]:
        # У экономики нет мягкого удаления: она живёт и умирает вместе с
        # проектом, а не отдельно от него.
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


@router.patch("/{project_id}", response_model=ProjectRead, summary="Изменить проект")
async def update_project(
    project_id: uuid.UUID,
    payload: ProjectUpdate,
    session: SessionDep,
    ctx: WriteDep,
) -> ProjectRead:
    repo = ProjectRepository(session, ctx)
    project = await repo.get_or_404(project_id)

    if payload.expected_version is not None and project.version != payload.expected_version:
        # Проект редактируют вдвоём чаще, чем кажется: специалист в вебе и
        # он же в боте. Молча затирать чужое изменение нельзя (v0.4 §100).
        raise ConflictError(
            details={
                "expected_version": payload.expected_version,
                "actual_version": project.version,
            }
        )

    # exclude_unset важен: без него незаполненные поля пришли бы как None и
    # стёрли бы уже сохранённые значения.
    updates = payload.model_dump(exclude={"expected_version"}, exclude_unset=True)
    for key, value in updates.items():
        setattr(project, key, value)

    project.version += 1
    await session.flush()
    # updated_at проставляет база, и после flush значение в сессии просрочено.
    # Без явного обновления ответ пытался бы догрузить его лениво — в чужом
    # контексте, где асинхронный ввод-вывод уже недоступен.
    await session.refresh(project)

    return ProjectRead.model_validate(project)


@router.delete(
    "/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить проект",
)
async def delete_project(project_id: uuid.UUID, session: SessionDep, ctx: WriteDep) -> None:
    """Мягкое удаление (v0.3 §61).

    Запись остаётся в базе и перестаёт появляться в выборках. Так удалённый по
    ошибке проект можно вернуть, а история аудитов и конкурентов не исчезает
    вместе с ним в тот же миг. Окончательное удаление — отдельная процедура по
    истечении срока хранения.
    """
    await ProjectRepository(session, ctx).soft_delete(project_id)


@router.get(
    "/{project_id}/progress",
    response_model=ProgressRead,
    summary="Прогресс проекта по шагам",
)
async def get_progress(
    project_id: uuid.UUID, session: SessionDep, ctx: TenantDep
) -> ProgressRead:
    repo = ProjectRepository(session, ctx)
    project = await repo.get_or_404(project_id)

    economics = await _load_economics(session, ctx, project_id)
    audit = await _latest_audit(session, ctx, project_id)

    progress = evaluate_progress(
        ProgressInput(
            has_website=bool(project.website_url),
            audit_status=audit.status.value if audit else None,
            audit_has_blocking_issues=_has_blocking_issues(audit),
            competitors_checked=await _count_checked_competitors(session, ctx, project_id),
            economics_mode=evaluate(_to_input(economics)).mode,
            # Рекламный кабинет до прохождения проверок безопасности не
            # подключается ни при каких условиях (v0.4 §2.1).
            ad_account_connected=False,
        )
    )

    return ProgressRead(
        project_id=project_id,
        steps=[
            StepRead(key=s.key, label=s.label, state=s.state, hint=s.hint)
            for s in progress.steps
        ],
        current=progress.current,
        completed_count=progress.completed_count,
        total_count=len(progress.steps),
        next_action=progress.next_action,
    )


async def _latest_audit(
    session: SessionDep, ctx: TenantDep, project_id: uuid.UUID
) -> SiteAudit | None:
    stmt = (
        select(SiteAudit)
        .where(SiteAudit.organization_id == ctx.organization_id)
        .where(SiteAudit.project_id == project_id)
        .order_by(SiteAudit.created_at.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def _count_checked_competitors(
    session: SessionDep, ctx: TenantDep, project_id: uuid.UUID
) -> int:
    """Сколько конкурентов уже разобрано.

    Считаются только завершённые: конкурент в очереди ещё ничего не добавил к
    исследованию.
    """
    stmt = (
        select(func.count())
        .select_from(Competitor)
        .where(Competitor.organization_id == ctx.organization_id)
        .where(Competitor.project_id == project_id)
        .where(Competitor.status == ModuleStatus.COMPLETED)
    )
    return int((await session.execute(stmt)).scalar_one())


def _has_blocking_issues(audit: SiteAudit | None) -> bool:
    if audit is None:
        return False
    return any(issue.get("severity") == "critical" for issue in (audit.issues or []))


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
        input=economics,
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
        input=economics,
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

