"""Вход, выход и текущий пользователь."""

from __future__ import annotations

import logging
from datetime import timedelta

from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select

from ...config import Settings
from ...errors import AppError
from ...models import Organization, User
from ...services import yandex_id
from ...services.auth import (
    COOKIE_NAME,
    issue_session,
    revoke_session,
)
from ...tenancy.context import Role
from ..deps import AuthDep, SessionDep, SettingsDep
from ..schemas import CurrentUserRead

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

#: Кука со случайным значением, которым сверяется ответ Яндекса. Живёт минуты:
#: столько занимает вход, и дольше держать её незачем.
STATE_COOKIE = "ads_os_oauth_state"
STATE_TTL_SECONDS = 600


class LoginNotConfiguredError(AppError):
    status_code = 503
    error_code = "login_not_configured"
    message = "Вход через Яндекс не настроен на этом стенде"


class AccessDeniedError(AppError):
    """Человек вошёл в Яндексе, но участником не является.

    Регистрация «с улицы» не предусмотрена: доступ выдаёт владелец, добавляя
    участника. Иначе любой обладатель аккаунта Яндекса заводил бы себе учётную
    запись в системе, управляющей рекламными бюджетами.
    """

    status_code = 403
    error_code = "access_denied"
    message = "Доступ не выдан. Попросите владельца добавить вас в участники"


def _redirect_uri(settings: Settings) -> str:
    """Адрес возврата после входа.

    Строится из адреса приложения, а не приходит параметром: иначе его можно
    было бы подменить и увести код авторизации на чужой сервер.
    """
    return f"{settings.app_base_url.rstrip('/')}/api/v1/auth/callback"


@router.get("/login", summary="Начать вход через Яндекс")
async def login(settings: SettingsDep) -> RedirectResponse:
    if not settings.yandex_oauth_client_id:
        raise LoginNotConfiguredError()

    state = yandex_id.new_state()
    response = RedirectResponse(
        yandex_id.authorize_url(
            client_id=settings.yandex_oauth_client_id,
            redirect_uri=_redirect_uri(settings),
            state=state,
        ),
        status_code=307,
    )
    response.set_cookie(
        STATE_COOKIE,
        state,
        max_age=STATE_TTL_SECONDS,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
        path="/",
    )
    return response


@router.get("/callback", summary="Возврат после входа через Яндекс")
async def callback(
    request: Request,
    db: SessionDep,
    settings: SettingsDep,
    code: str | None = None,
    state: str | None = None,
) -> RedirectResponse:
    if not settings.yandex_oauth_client_id:
        raise LoginNotConfiguredError()

    expected = request.cookies.get(STATE_COOKIE)
    if not state or not expected or state != expected:
        # Ответ пришёл не на наш запрос. Так выглядит попытка подсунуть чужой
        # код авторизации, и продолжать нельзя.
        logger.warning("вход отклонён: не совпало значение state")
        raise AccessDeniedError()

    if not code:
        raise AccessDeniedError()

    try:
        access_token = await yandex_id.exchange_code(
            code,
            client_id=settings.yandex_oauth_client_id,
            client_secret=settings.yandex_oauth_client_secret,
            redirect_uri=_redirect_uri(settings),
        )
        profile = await yandex_id.fetch_user(access_token)
    except yandex_id.YandexAuthError as exc:
        logger.warning("вход через Яндекс не состоялся", extra={"reason": exc.reason})
        raise AccessDeniedError() from exc

    user = await _find_member(db, profile)

    if user is None:
        user = await _bootstrap_owner(db, profile, settings)

    if user is None:
        logger.info("вход отклонён: участник не найден", extra={"email": profile.email})
        raise AccessDeniedError()

    # Идентификатор Яндекса запоминается при первом входе: дальше сопоставление
    # идёт по нему, и смена почты в аккаунте не отрезает человека от системы.
    if not user.yandex_id:
        user.yandex_id = profile.id

    issued = await issue_session(
        db,
        user,
        ttl=timedelta(days=settings.session_ttl_days),
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
    )

    logger.info("вход выполнен", extra={"user_id": str(user.id)})

    response = RedirectResponse(settings.app_base_url, status_code=303)
    response.delete_cookie(STATE_COOKIE, path="/")
    response.set_cookie(
        COOKIE_NAME,
        issued.token,
        max_age=settings.session_ttl_days * 24 * 3600,
        # httponly обязателен: кука не должна читаться скриптом на странице,
        # иначе любая уязвимость в вёрстке превращается в кражу сессии.
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
        path="/",
    )
    return response


@router.post("/logout", status_code=204, summary="Выйти")
async def logout(auth: AuthDep, db: SessionDep, settings: SettingsDep) -> Response:
    await revoke_session(db, auth.session)

    response = Response(status_code=204)
    response.delete_cookie(COOKIE_NAME, path="/")
    return response


@router.get("/me", response_model=CurrentUserRead, summary="Текущий пользователь")
async def me(auth: AuthDep, db: SessionDep) -> CurrentUserRead:
    organization = (
        await db.execute(
            select(Organization).where(Organization.id == auth.session.organization_id)
        )
    ).scalar_one()

    return CurrentUserRead(
        id=auth.user.id,
        email=auth.user.email,
        full_name=auth.user.full_name,
        role=auth.user.role.value,
        organization_id=organization.id,
        organization_name=organization.name,
    )


async def _find_member(db: SessionDep, profile: yandex_id.YandexUser) -> User | None:
    """Ищет участника: сначала по идентификатору Яндекса, затем по почте."""
    by_id = (
        await db.execute(
            select(User)
            .where(User.yandex_id == profile.id)
            .where(User.deleted_at.is_(None))
        )
    ).scalar_one_or_none()

    if by_id is not None:
        return by_id if by_id.is_active else None

    by_email = (
        await db.execute(
            select(User)
            .where(func.lower(User.email) == profile.email)
            .where(User.deleted_at.is_(None))
        )
    ).scalar_one_or_none()

    if by_email is None or not by_email.is_active:
        return None

    return by_email


async def _bootstrap_owner(
    db: SessionDep, profile: yandex_id.YandexUser, settings: Settings
) -> User | None:
    """Создаёт первого владельца — один раз за всё время.

    Первого владельца некому пригласить: он и есть тот, кто приглашает
    остальных. Поэтому его почта задаётся настройкой сервера, и дверь
    закрывается сразу же, как только владелец появился: второй раз этот путь не
    сработает, даже если настройку не убрать.
    """
    expected = settings.bootstrap_owner_email.strip().lower()
    if not expected or profile.email != expected:
        return None

    existing_owner = (
        await db.execute(select(func.count()).select_from(User).where(User.role == Role.OWNER))
    ).scalar_one()

    if existing_owner:
        logger.warning(
            "попытка повторного создания владельца отклонена",
            extra={"email": profile.email},
        )
        return None

    organization = (
        await db.execute(
            select(Organization).where(Organization.deleted_at.is_(None)).limit(1)
        )
    ).scalar_one_or_none()

    if organization is None:
        organization = Organization(name="Моя организация", slug="main")
        db.add(organization)
        await db.flush()

    user = User(
        organization_id=organization.id,
        email=profile.email,
        full_name=profile.display_name,
        role=Role.OWNER,
        yandex_id=profile.id,
    )
    db.add(user)
    await db.flush()

    logger.info("создан первый владелец", extra={"user_id": str(user.id)})
    return user
