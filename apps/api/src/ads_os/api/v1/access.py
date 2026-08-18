"""Кому открыт проект.

Владелец вписывает почту — человек получает доступ к этому проекту и ни к
какому больше. Учётную запись заводить отдельно не нужно: она создаётся здесь
же, а личность подтвердит Яндекс при первом входе.

Почему доступ выдаётся именно так. Раньше участник добавлялся в организацию
целиком и видел всё: и своих клиентов, и чужих. Для агентства это неверно, а
для самого клиента, которому дали посмотреть на свой проект, — недопустимо.
Список проектов и есть граница видимости, и проходит она в репозитории, а не
в проверках по месту (см. `TenantRepository.scoped`).

Выдавать и отзывать доступ может только владелец. Специалист, который может
открыть проект кому угодно, — это отсутствие разграничения, просто в два шага.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, status
from sqlalchemy import select

from ...errors import AppError, ForbiddenError, NotFoundError
from ...models import Project, ProjectAccess, User
from ...models.activity import ActivityAction
from ...services import yandex_email
from ...services.activity import record
from ...services.auth import revoke_all_for_user
from ...tenancy.context import Role
from ...tenancy.repository import TenantRepository
from ..deps import SessionDep, TenantDep, WriteDep
from ..schemas import (
    ProjectAccessCreate,
    ProjectAccessList,
    ProjectAccessRead,
    ProjectAccessUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["access"])

#: Сколько человек может быть у одного проекта. Ограничение не техническое:
#: доступ, выданный тридцати людям, перестаёт быть доступом и становится общим
#: местом, за которым никто не следит.
MAX_GUESTS = 20


class BadEmailError(AppError):
    status_code = 422
    error_code = "bad_email"
    message = "Это не похоже на адрес почты"


class TooManyGuestsError(AppError):
    status_code = 409
    error_code = "too_many_guests"
    message = f"К одному проекту нельзя открыть доступ более чем {MAX_GUESTS} людям"


class ProjectRepository(TenantRepository[Project]):
    model = Project


def _require_owner(ctx: TenantDep) -> None:
    """Доступы раздаёт владелец, и только он.

    Специалист, который может открыть проект кому угодно, — это отсутствие
    разграничения, просто выполненное в два шага.
    """
    if not ctx.is_owner:
        raise ForbiddenError("Доступ к проекту выдаёт владелец организации")


@router.get(
    "/{project_id}/access",
    response_model=ProjectAccessList,
    summary="Кому открыт проект",
)
async def list_access(
    project_id: uuid.UUID, session: SessionDep, ctx: TenantDep
) -> ProjectAccessList:
    project = await ProjectRepository(session, ctx).get_or_404(project_id)

    rows = (
        (
            await session.execute(
                select(ProjectAccess, User)
                .join(User, User.id == ProjectAccess.user_id)
                .where(ProjectAccess.project_id == project.id)
                .where(ProjectAccess.organization_id == ctx.organization_id)
                .order_by(ProjectAccess.created_at)
            )
        )
        .tuples()
        .all()
    )

    # Владельцы и участники, видящие все проекты, в списке не показываются: они
    # видят проект не по этой записи, и «отозвать» их отсюда невозможно.
    # Показывать кнопку, которая ничего не делает, — худший вид интерфейса.
    return ProjectAccessList(
        items=[
            ProjectAccessRead(
                user_id=user.id,
                email=user.email,
                full_name=user.full_name,
                role=user.role.value,
                is_active=user.is_active,
                last_login_at=user.last_login_at,
                granted_at=access.created_at,
            )
            for access, user in rows
        ],
        total=len(rows),
    )


@router.post(
    "/{project_id}/access",
    response_model=ProjectAccessRead,
    status_code=status.HTTP_201_CREATED,
    summary="Открыть доступ к проекту по почте",
)
async def grant_access(
    project_id: uuid.UUID,
    payload: ProjectAccessCreate,
    session: SessionDep,
    ctx: WriteDep,
) -> ProjectAccessRead:
    _require_owner(ctx)

    project = await ProjectRepository(session, ctx).get_or_404(project_id)

    email = payload.email.strip()
    if not yandex_email.looks_like_email(email):
        raise BadEmailError()

    existing = (
        (
            await session.execute(
                select(ProjectAccess).where(ProjectAccess.project_id == project.id)
            )
        )
        .scalars()
        .all()
    )
    if len(existing) >= MAX_GUESTS:
        raise TooManyGuestsError()

    user = await _find_or_create(session, email, payload, organization_id=ctx.organization_id)

    if any(row.user_id == user.id for row in existing):
        # Повторная выдача того же доступа — не ошибка: владелец мог просто не
        # увидеть человека в списке. Отвечаем тем же, что и в первый раз.
        return _read(user, granted_at=user.created_at)

    access = ProjectAccess(
        organization_id=ctx.organization_id,
        user_id=user.id,
        project_id=project.id,
        granted_by=ctx.user_id,
    )
    session.add(access)
    await session.flush()

    await record(
        session,
        ctx,
        ActivityAction.MEMBER_ADDED,
        subject=f"Открыт доступ к проекту: {user.email}",
        actor_name=ctx.user_name,
        project_id=project.id,
    )

    logger.info(
        "доступ к проекту выдан",
        extra={"project_id": str(project.id), "user_id": str(user.id)},
    )

    return _read(user, granted_at=access.created_at)


@router.delete(
    "/{project_id}/access/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Закрыть доступ к проекту",
)
async def revoke_access(
    project_id: uuid.UUID, user_id: uuid.UUID, session: SessionDep, ctx: WriteDep
) -> None:
    _require_owner(ctx)

    project = await ProjectRepository(session, ctx).get_or_404(project_id)

    access = (
        await session.execute(
            select(ProjectAccess)
            .where(ProjectAccess.project_id == project.id)
            .where(ProjectAccess.user_id == user_id)
            .where(ProjectAccess.organization_id == ctx.organization_id)
        )
    ).scalar_one_or_none()

    if access is None:
        raise NotFoundError()

    await session.delete(access)
    await session.flush()

    # Отзыв должен действовать сразу. Список открытых проектов читается при
    # каждом запросе, так что человек теряет проект немедленно; но если это был
    # его единственный проект, ему нечего делать внутри вовсе — и держать
    # открытую сессию незачем.
    remaining = (
        await session.execute(select(ProjectAccess).where(ProjectAccess.user_id == user_id))
    ).scalars().all()

    user = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()

    if not remaining and user is not None and not user.all_projects:
        await revoke_all_for_user(session, user_id)

    await record(
        session,
        ctx,
        ActivityAction.MEMBER_REMOVED,
        subject=f"Закрыт доступ к проекту: {user.email if user else user_id}",
        actor_name=ctx.user_name,
        project_id=project.id,
    )

    logger.info(
        "доступ к проекту закрыт",
        extra={"project_id": str(project.id), "user_id": str(user_id)},
    )


async def _find_or_create(
    session: SessionDep,
    email: str,
    payload: ProjectAccessCreate,
    *,
    organization_id: uuid.UUID,
) -> User:
    """Находит участника по почте или заводит нового.

    Сравнение идёт в приведённом виде: `ivan.petrov@ya.ru` и
    `ivan-petrov@yandex.ru` — один и тот же ящик, и завести по ним двух
    участников значило бы, что человек войдёт как один, а доступ выдан другому.
    """
    wanted = yandex_email.normalize(email)

    people = (
        (
            await session.execute(
                select(User)
                .where(User.organization_id == organization_id)
                .where(User.deleted_at.is_(None))
            )
        )
        .scalars()
        .all()
    )

    for user in people:
        if yandex_email.normalize(user.email) == wanted:
            return user

    user = User(
        organization_id=organization_id,
        # Хранится введённый адрес, а не приведённый: человек должен видеть в
        # списке то, что сам вписал.
        email=email.lower(),
        full_name=(payload.full_name or "").strip() or email,
        role=Role(payload.role),
        # Заведённый здесь человек видит только те проекты, которые ему открыли.
        # Ради этого всё и затевалось: доступ к одному проекту не должен быть
        # доступом ко всем остальным.
        all_projects=False,
    )
    session.add(user)
    await session.flush()

    logger.info("заведён участник по приглашению", extra={"user_id": str(user.id)})
    return user


def _read(user: User, *, granted_at: object) -> ProjectAccessRead:
    from datetime import datetime

    return ProjectAccessRead(
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role.value,
        is_active=user.is_active,
        last_login_at=user.last_login_at,
        granted_at=granted_at if isinstance(granted_at, datetime) else None,
    )


@router.patch(
    "/{project_id}/access/{user_id}",
    response_model=ProjectAccessRead,
    summary="Изменить роль в проекте",
)
async def change_role(
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: ProjectAccessUpdate,
    session: SessionDep,
    ctx: WriteDep,
) -> ProjectAccessRead:
    """Меняет роль человека, которому проект уже открыт.

    Без этого поправить ошибку можно было бы только закрыв доступ и выдав
    заново — а это отзыв сессий и запись в журнале о том, чего не было.
    """
    _require_owner(ctx)

    project = await ProjectRepository(session, ctx).get_or_404(project_id)

    access = (
        await session.execute(
            select(ProjectAccess)
            .where(ProjectAccess.project_id == project.id)
            .where(ProjectAccess.user_id == user_id)
            .where(ProjectAccess.organization_id == ctx.organization_id)
        )
    ).scalar_one_or_none()

    if access is None:
        raise NotFoundError()

    user = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        raise NotFoundError()

    # Владельца понижать отсюда нельзя: он видит проект не по этой записи, и
    # смена роли здесь оставила бы организацию без ответственного.
    if user.role is Role.OWNER:
        raise ForbiddenError("Роль владельца организации меняется в настройках")

    user.role = Role(payload.role)
    await session.flush()

    await record(
        session,
        ctx,
        ActivityAction.MEMBER_UPDATED,
        subject=f"{user.email}: {payload.role}",
        actor_name=ctx.user_name,
        project_id=project.id,
    )

    return _read(user, granted_at=access.created_at)
