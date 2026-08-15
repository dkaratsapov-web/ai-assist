"""Сессии: выпуск, проверка, отзыв.

Модуль намеренно ничего не знает про Яндекс и вообще про способ входа. Его
задача начинается там, где личность уже подтверждена: выдать сессию, узнать её
по токену, отозвать.

Разделение не косметическое. Способ входа со временем меняется — добавится
второй провайдер, появится вход по ссылке, что-то отвалится. Механизм сессий
при этом остаётся тем же, и трогать его при каждой такой смене не придётся.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession as DbSession

from ..db.base import utcnow
from ..models import Session, User
from ..tenancy.context import Role, TenantContext

#: Длина случайной части токена в байтах. 32 байта — 256 бит энтропии: перебор
#: невозможен, а длина куки остаётся разумной.
TOKEN_BYTES = 32

#: Имя куки. Префикс `__Host-` не используется намеренно: он требует, чтобы кука
#: ставилась без домена и только по HTTPS, а локальная разработка идёт по HTTP.
COOKIE_NAME = "ads_os_session"


def hash_token(token: str) -> str:
    """Хеш токена для хранения в базе.

    Обычный SHA-256 без соли — здесь этого достаточно и это правильно. Токен
    случайный и длинный, словарной атаки на него не существует, а замедляющая
    функция вроде bcrypt заставила бы считать хеш на каждом запросе.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class IssuedSession:
    """Выпущенная сессия.

    Открытый токен возвращается ровно один раз — в момент выпуска. Дальше он
    существует только у пользователя в куке.
    """

    token: str
    session: Session


async def issue_session(
    db: DbSession,
    user: User,
    *,
    ttl: timedelta,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> IssuedSession:
    """Выпускает сессию для пользователя."""
    token = secrets.token_urlsafe(TOKEN_BYTES)

    session = Session(
        user_id=user.id,
        organization_id=user.organization_id,
        token_hash=hash_token(token),
        expires_at=utcnow() + ttl,
        last_seen_at=utcnow(),
        # Длинный User-Agent обрезается: он нужен только чтобы человек узнал
        # свой вход в списке, а не для точной идентификации браузера.
        user_agent=(user_agent or "")[:200] or None,
        ip_address=(ip_address or "")[:45] or None,
    )
    db.add(session)
    await db.flush()

    user.last_login_at = utcnow()

    return IssuedSession(token=token, session=session)


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    """Пользователь текущего запроса вместе с его сессией."""

    user: User
    session: Session

    @property
    def context(self) -> TenantContext:
        return TenantContext(
            organization_id=self.session.organization_id,
            user_id=self.user.id,
            role=self.user.role,
            user_name=self.user.full_name,
        )


async def resolve_session(db: DbSession, token: str) -> AuthenticatedUser | None:
    """Находит живую сессию по токену.

    Возвращает None во всех случаях отказа — истёкшая, отозванная, удалённый
    или отключённый пользователь. Различать их в ответе наружу не нужно: для
    пользователя это одно и то же событие «вы не вошли», а для подбирающего
    чужие токены разница была бы подсказкой.
    """
    session = (
        await db.execute(select(Session).where(Session.token_hash == hash_token(token)))
    ).scalar_one_or_none()

    if session is None or session.revoked_at is not None:
        return None

    if session.expires_at <= utcnow():
        return None

    user = (
        await db.execute(select(User).where(User.id == session.user_id))
    ).scalar_one_or_none()

    if user is None or not user.is_active or user.deleted_at is not None:
        # Отключённый участник теряет доступ немедленно, не дожидаясь конца
        # срока сессии. Ради этого сессии и хранятся на сервере.
        return None

    return AuthenticatedUser(user=user, session=session)


#: Насколько часто обновляется отметка последней активности. Писать её на
#: каждый запрос значит превращать чтение в запись и грузить базу без нужды.
LAST_SEEN_INTERVAL = timedelta(minutes=5)


def touch(session: Session, *, now: datetime | None = None) -> bool:
    """Обновляет отметку активности, если прошло достаточно времени.

    Возвращает True, если отметка изменилась.
    """
    moment = now or utcnow()
    if session.last_seen_at is not None and moment - session.last_seen_at < LAST_SEEN_INTERVAL:
        return False
    session.last_seen_at = moment
    return True


async def revoke_session(db: DbSession, session: Session) -> None:
    """Завершает одну сессию — обычный выход."""
    session.revoked_at = utcnow()
    await db.flush()


async def revoke_all_for_user(db: DbSession, user_id: object) -> int:
    """Завершает все сессии пользователя.

    Нужно при отключении участника: иначе он останется внутри до истечения
    срока, то есть отключение работало бы с задержкой в дни.
    """
    sessions = (
        (
            await db.execute(
                select(Session)
                .where(Session.user_id == user_id)
                .where(Session.revoked_at.is_(None))
            )
        )
        .scalars()
        .all()
    )

    for session in sessions:
        session.revoked_at = utcnow()

    await db.flush()
    return len(sessions)


def is_owner(user: User) -> bool:
    return user.role is Role.OWNER
