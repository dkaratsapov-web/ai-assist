"""Организация: состав, лимиты и режим работы стенда."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from ...errors import NotFoundError
from ...models import Organization, Project, User
from ..deps import SessionDep, SettingsDep, TenantDep
from ..schemas import MemberRead, OrganizationRead, PlanRead

router = APIRouter(tags=["organization"])


@router.get("/organization", response_model=OrganizationRead, summary="Моя организация")
async def get_organization(
    session: SessionDep, ctx: TenantDep, settings: SettingsDep
) -> OrganizationRead:
    """Сведения о своей организации.

    Идентификатор берётся из контекста, а не из адреса запроса: организация,
    которую можно указать параметром, — это готовый способ заглянуть в чужую
    (v0.3 §93).
    """
    organization = (
        await session.execute(
            select(Organization)
            .where(Organization.id == ctx.organization_id)
            .where(Organization.deleted_at.is_(None))
            .options(selectinload(Organization.plan))
        )
    ).scalar_one_or_none()

    if organization is None:
        raise NotFoundError()

    members = (
        (
            await session.execute(
                select(User)
                .where(User.organization_id == ctx.organization_id)
                .where(User.deleted_at.is_(None))
                .order_by(User.created_at)
            )
        )
        .scalars()
        .all()
    )

    projects_count = int(
        (
            await session.execute(
                select(func.count())
                .select_from(Project)
                .where(Project.organization_id == ctx.organization_id)
                .where(Project.deleted_at.is_(None))
            )
        ).scalar_one()
    )

    plan = organization.plan

    return OrganizationRead(
        id=organization.id,
        name=organization.name,
        slug=organization.slug,
        projects_count=projects_count,
        members=[
            MemberRead(
                id=user.id,
                email=user.email,
                full_name=user.full_name,
                role=user.role.value,
                mfa_enabled=user.mfa_enabled,
                is_active=user.is_active,
            )
            for user in members
        ],
        plan=(
            PlanRead(
                max_projects=plan.max_projects,
                max_users=plan.max_users,
                ai_usage_limit=plan.ai_usage_limit,
                crawler_pages_limit=plan.crawler_pages_limit,
                retention_days=plan.retention_days,
            )
            if plan is not None
            else None
        ),
        # Режим работы стенда показывается прямо, а не прячется в настройках
        # сервера: по нему видно, что результаты не являются выводами настоящей
        # модели и что рекламный кабинет не подключён.
        app_env=settings.app_env,
        ai_provider=settings.ai_provider,
        ad_platform_adapter=settings.ad_platform_adapter,
    )
