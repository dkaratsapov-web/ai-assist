"""Сессии и вход.

Здесь проверяется не удобство, а граница: ошибка в этом файле означает чужой
доступ к чужим данным. Поэтому проверяются в первую очередь отказы, а не
успешный сценарий.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from ads_os.db.base import utcnow
from ads_os.models import Organization, Session, User
from ads_os.services.auth import (
    LAST_SEEN_INTERVAL,
    hash_token,
    issue_session,
    resolve_session,
    revoke_all_for_user,
    revoke_session,
    touch,
)

from .conftest import make_user

TTL = timedelta(days=14)


@pytest.fixture
async def user(
    session: AsyncSession, two_organizations: tuple[Organization, Organization]
) -> User:
    org, _ = two_organizations
    created = await make_user(session, org, "specialist@example.com")
    await session.commit()
    return created


class TestВыпускСессии:
    async def test_токен_не_хранится_в_открытом_виде(
        self, session: AsyncSession, user: User
    ) -> None:
        """Утечка дампа базы не должна давать возможность войти чужой сессией."""
        issued = await issue_session(session, user, ttl=TTL)

        assert issued.session.token_hash != issued.token
        assert issued.session.token_hash == hash_token(issued.token)

    async def test_каждый_выпуск_даёт_новый_токен(
        self, session: AsyncSession, user: User
    ) -> None:
        first = await issue_session(session, user, ttl=TTL)
        second = await issue_session(session, user, ttl=TTL)

        assert first.token != second.token

    async def test_организация_берётся_у_пользователя(
        self, session: AsyncSession, user: User
    ) -> None:
        """Организацию нельзя выбрать при входе — иначе это способ войти в чужую."""
        issued = await issue_session(session, user, ttl=TTL)

        assert issued.session.organization_id == user.organization_id

    async def test_отмечается_время_входа(self, session: AsyncSession, user: User) -> None:
        await issue_session(session, user, ttl=TTL)

        assert user.last_login_at is not None

    async def test_длинный_user_agent_обрезается(
        self, session: AsyncSession, user: User
    ) -> None:
        issued = await issue_session(session, user, ttl=TTL, user_agent="x" * 500)

        assert issued.session.user_agent is not None
        assert len(issued.session.user_agent) == 200


class TestПроверкаСессии:
    async def test_живая_сессия_узнаётся(self, session: AsyncSession, user: User) -> None:
        issued = await issue_session(session, user, ttl=TTL)
        await session.commit()

        auth = await resolve_session(session, issued.token)

        assert auth is not None
        assert auth.user.id == user.id
        assert auth.context.organization_id == user.organization_id

    async def test_чужой_токен_не_подходит(self, session: AsyncSession, user: User) -> None:
        await issue_session(session, user, ttl=TTL)
        await session.commit()

        assert await resolve_session(session, "выдуманный-токен") is None

    async def test_истёкшая_сессия_не_подходит(
        self, session: AsyncSession, user: User
    ) -> None:
        issued = await issue_session(session, user, ttl=-timedelta(seconds=1))
        await session.commit()

        assert await resolve_session(session, issued.token) is None

    async def test_отозванная_сессия_не_подходит(
        self, session: AsyncSession, user: User
    ) -> None:
        issued = await issue_session(session, user, ttl=TTL)
        await revoke_session(session, issued.session)
        await session.commit()

        assert await resolve_session(session, issued.token) is None

    async def test_отключённый_участник_теряет_доступ_немедленно(
        self, session: AsyncSession, user: User
    ) -> None:
        """Ради этого сессии и хранятся на сервере, а не в самоподписанном токене."""
        issued = await issue_session(session, user, ttl=TTL)
        user.is_active = False
        await session.commit()

        assert await resolve_session(session, issued.token) is None

    async def test_удалённый_участник_теряет_доступ(
        self, session: AsyncSession, user: User
    ) -> None:
        issued = await issue_session(session, user, ttl=TTL)
        user.deleted_at = utcnow()
        await session.commit()

        assert await resolve_session(session, issued.token) is None


class TestОтзыв:
    async def test_отзываются_все_сессии_участника(
        self, session: AsyncSession, user: User
    ) -> None:
        first = await issue_session(session, user, ttl=TTL)
        second = await issue_session(session, user, ttl=TTL)
        await session.commit()

        count = await revoke_all_for_user(session, user.id)
        await session.commit()

        assert count == 2
        assert await resolve_session(session, first.token) is None
        assert await resolve_session(session, second.token) is None

    async def test_чужие_сессии_не_трогаются(
        self,
        session: AsyncSession,
        user: User,
        two_organizations: tuple[Organization, Organization],
    ) -> None:
        _, other_org = two_organizations
        stranger = await make_user(session, other_org, "stranger@example.com")
        mine = await issue_session(session, user, ttl=TTL)
        theirs = await issue_session(session, stranger, ttl=TTL)
        await session.commit()

        await revoke_all_for_user(session, user.id)
        await session.commit()

        assert await resolve_session(session, mine.token) is None
        assert await resolve_session(session, theirs.token) is not None


class TestОтметкаАктивности:
    def test_свежая_отметка_не_обновляется(self) -> None:
        """Писать на каждый запрос значит превращать чтение в запись."""
        session = Session(last_seen_at=utcnow())

        assert touch(session) is False

    def test_старая_отметка_обновляется(self) -> None:
        session = Session(last_seen_at=utcnow() - LAST_SEEN_INTERVAL - timedelta(seconds=1))

        assert touch(session) is True

    def test_пустая_отметка_проставляется(self) -> None:
        session = Session(last_seen_at=None)

        assert touch(session) is True
        assert session.last_seen_at is not None
