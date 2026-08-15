"""Сводка по всем проектам — главный экран.

Всё считается на сервере одним набором запросов, независимо от числа проектов.
Наивная реализация просила бы для каждого проекта его аудит, экономику,
конкурентов и прогресс — то есть четыре запроса на строку. У агентства с
тридцатью клиентами это сто двадцать запросов на открытие главной.

Чего здесь нет и не будет, пока не подключён рекламный кабинет: расходов,
лидов, продаж и любых денежных показателей. Показывать нули там, где мы просто
не знаем, — худший из возможных вариантов: по ним принимают решения (v0.3 §140).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter
from sqlalchemy import func, select

from ...models import Competitor, Project, ProjectEconomics, SiteAudit
from ...models.audit import ModuleStatus
from ...services.economics import EconomicsInput
from ...services.economics import evaluate as evaluate_economics
from ...services.progress import ProgressInput, StepState
from ...services.progress import evaluate as evaluate_progress
from ...tenancy.repository import TenantRepository
from ..deps import SessionDep, TenantDep
from ..schemas import OverviewRead, ProjectSummaryRead

router = APIRouter(tags=["overview"])


class ProjectRepository(TenantRepository[Project]):
    model = Project


@router.get("/overview", response_model=OverviewRead, summary="Сводка по проектам")
async def get_overview(session: SessionDep, ctx: TenantDep) -> OverviewRead:
    repo = ProjectRepository(session, ctx)
    projects = await repo.list(limit=200, offset=0)

    if not projects:
        return OverviewRead(
            projects=[], total=0, needs_attention=0, ad_platform_connected=False
        )

    project_ids = [p.id for p in projects]

    audits = await _latest_audits(session, ctx, project_ids)
    economics = await _economics(session, ctx, project_ids)
    rivals = await _competitor_counts(session, ctx, project_ids)

    summaries: list[ProjectSummaryRead] = []
    needs_attention = 0

    for project in projects:
        audit = audits.get(project.id)
        mode = evaluate_economics(economics.get(project.id, EconomicsInput())).mode

        progress = evaluate_progress(
            ProgressInput(
                has_website=bool(project.website_url),
                audit_status=audit.status.value if audit else None,
                audit_has_blocking_issues=_has_blocking_issues(audit),
                competitors_checked=rivals.get(project.id, 0),
                economics_mode=mode,
                # Рекламный кабинет до прохождения проверок безопасности не
                # подключается ни при каких условиях (v0.4 §2.1).
                ad_account_connected=False,
            )
        )

        current = next(s for s in progress.steps if s.key is progress.current)
        # Внимания требует то, что сломалось или чего система ждёт от человека.
        # Шаг в ожидании чужой готовности вниманием не считается — иначе
        # «требуют внимания» окажутся все проекты сразу и счётчик обесценится.
        if current.state in (StepState.ACTIVE, StepState.ERROR):
            needs_attention += 1

        summaries.append(
            ProjectSummaryRead(
                id=project.id,
                name=project.name,
                website_url=project.website_url,
                status=project.status,
                current_step=progress.current,
                current_step_label=current.label,
                completed_count=progress.completed_count,
                total_count=len(progress.steps),
                next_action=progress.next_action,
                audit_status=audit.status if audit else None,
                audit_score=audit.score if audit else None,
                can_launch=not _has_blocking_issues(audit),
                economics_mode=mode,
                competitors_checked=rivals.get(project.id, 0),
            )
        )

    return OverviewRead(
        projects=summaries,
        total=len(summaries),
        needs_attention=needs_attention,
        ad_platform_connected=False,
    )


async def _latest_audits(
    session: SessionDep, ctx: TenantDep, project_ids: list[uuid.UUID]
) -> dict[uuid.UUID, SiteAudit]:
    """Последний аудит каждого проекта — одним запросом.

    Отбор идёт по максимальной дате создания внутри проекта. Забирать все
    аудиты и выбирать последний в Python нельзя: история хранится целиком и со
    временем станет заметно длиннее списка проектов.
    """
    latest = (
        select(
            SiteAudit.project_id.label("project_id"),
            func.max(SiteAudit.created_at).label("created_at"),
        )
        .where(SiteAudit.organization_id == ctx.organization_id)
        .where(SiteAudit.project_id.in_(project_ids))
        .group_by(SiteAudit.project_id)
        .subquery()
    )

    stmt = select(SiteAudit).join(
        latest,
        (SiteAudit.project_id == latest.c.project_id)
        & (SiteAudit.created_at == latest.c.created_at),
    )

    return {a.project_id: a for a in (await session.execute(stmt)).scalars().all()}


async def _economics(
    session: SessionDep, ctx: TenantDep, project_ids: list[uuid.UUID]
) -> dict[uuid.UUID, EconomicsInput]:
    stmt = (
        select(ProjectEconomics)
        .where(ProjectEconomics.organization_id == ctx.organization_id)
        .where(ProjectEconomics.project_id.in_(project_ids))
    )

    return {
        row.project_id: EconomicsInput(
            monthly_budget=row.monthly_budget,
            average_order_value=row.average_order_value,
            expected_value=row.expected_value,
            main_conversion=row.main_conversion.value if row.main_conversion else None,
            margin_percent=row.margin_percent,
            lead_to_sale_rate=row.lead_to_sale_rate,
            target_cac=row.target_cac,
            target_cpl=row.target_cpl,
            target_marketing_share=row.target_marketing_share,
        )
        for row in (await session.execute(stmt)).scalars().all()
    }


async def _competitor_counts(
    session: SessionDep, ctx: TenantDep, project_ids: list[uuid.UUID]
) -> dict[uuid.UUID, int]:
    stmt = (
        select(Competitor.project_id, func.count())
        .where(Competitor.organization_id == ctx.organization_id)
        .where(Competitor.project_id.in_(project_ids))
        .where(Competitor.status == ModuleStatus.COMPLETED)
        .group_by(Competitor.project_id)
    )

    return {row[0]: int(row[1]) for row in (await session.execute(stmt)).all()}


def _has_blocking_issues(audit: SiteAudit | None) -> bool:
    if audit is None:
        return False
    return any(issue.get("severity") == "critical" for issue in (audit.issues or []))
