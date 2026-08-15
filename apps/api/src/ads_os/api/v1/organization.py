"""Организация: состав, лимиты и режим работы стенда."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from ...errors import AppError, ConflictError, NotFoundError
from ...models import Organization, Project, User
from ...services.auth import revoke_all_for_user
from ...tenancy.context import Role
from ..deps import OwnerDep, SessionDep, SettingsDep, TenantDep
from ..schemas import MemberCreate, MemberRead, MemberUpdate, OrganizationRead, PlanRead

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
            _to_member(user) for user in members
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


@router.post(
    "/organization/members",
    response_model=MemberRead,
    status_code=status.HTTP_201_CREATED,
    summary="Добавить участника",
)
async def add_member(
    payload: MemberCreate, session: SessionDep, ctx: OwnerDep
) -> MemberRead:
    """Выдаёт человеку доступ.

    Приглашение по почте с одноразовой ссылкой не нужно: личность подтверждает
    Яндекс ID. Достаточно записать почту — при входе человек будет опознан по
    ней. Пока он не вошёл, запись означает ровно «доступ выдан, но не
    использован».
    """
    email = payload.email.strip().lower()

    existing = (
        await session.execute(
            select(User)
            .where(User.organization_id == ctx.organization_id)
            .where(func.lower(User.email) == email)
        )
    ).scalar_one_or_none()

    if existing is not None:
        raise ConflictError(details={"email": email})

    user = User(
        organization_id=ctx.organization_id,
        email=email,
        full_name=payload.full_name.strip(),
        role=Role(payload.role),
    )
    session.add(user)
    await session.flush()

    return _to_member(user)


@router.patch(
    "/organization/members/{member_id}",
    response_model=MemberRead,
    summary="Изменить участника",
)
async def update_member(
    member_id: uuid.UUID,
    payload: MemberUpdate,
    session: SessionDep,
    ctx: OwnerDep,
) -> MemberRead:
    user = await _member_or_404(session, ctx.organization_id, member_id)

    updates = payload.model_dump(exclude_unset=True)

    if "role" in updates and updates["role"] is not None:
        new_role = Role(updates.pop("role"))
        if user.role is Role.OWNER and new_role is not Role.OWNER:
            await _guard_last_owner(session, ctx.organization_id, user.id)
        user.role = new_role

    if updates.get("is_active") is False:
        if user.role is Role.OWNER:
            await _guard_last_owner(session, ctx.organization_id, user.id)
        # Отключение действует немедленно: иначе человек остался бы внутри до
        # истечения сессии, то есть отключение работало бы с задержкой в дни.
        await revoke_all_for_user(session, user.id)

    for key, value in updates.items():
        if value is not None:
            setattr(user, key, value)

    await session.flush()
    return _to_member(user)


class LastOwnerError(AppError):
    """Последнего владельца нельзя отключить или понизить.

    Иначе организация останется без того, кто может выдавать доступы, — и
    вернуть управление можно будет только через сервер.
    """

    status_code = 422
    error_code = "last_owner"
    message = "Это последний владелец. Сначала назначьте другого"


async def _guard_last_owner(
    session: SessionDep, organization_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    others = (
        await session.execute(
            select(func.count())
            .select_from(User)
            .where(User.organization_id == organization_id)
            .where(User.role == Role.OWNER)
            .where(User.is_active.is_(True))
            .where(User.deleted_at.is_(None))
            .where(User.id != user_id)
        )
    ).scalar_one()

    if not others:
        raise LastOwnerError()


async def _member_or_404(
    session: SessionDep, organization_id: uuid.UUID, member_id: uuid.UUID
) -> User:
    user = (
        await session.execute(
            select(User)
            .where(User.id == member_id)
            .where(User.organization_id == organization_id)
            .where(User.deleted_at.is_(None))
        )
    ).scalar_one_or_none()

    if user is None:
        raise NotFoundError()

    return user


def _to_member(user: User) -> MemberRead:
    return MemberRead(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role.value,
        is_active=user.is_active,
        has_logged_in=user.yandex_id is not None,
        last_login_at=user.last_login_at,
    )
