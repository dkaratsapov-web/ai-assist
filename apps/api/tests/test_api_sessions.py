"""Активные входы: список и завершение."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import timedelta
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from ads_os.api.deps import get_session
from ads_os.api.v1.auth import STATE_COOKIE
from ads_os.api.v1.sessions import describe_device
from ads_os.config import Settings, get_settings
from ads_os.main import create_app
from ads_os.models import Organization, User
from ads_os.services.auth import issue_session, resolve_session
from ads_os.services.yandex_id import YandexUser

from .conftest import make_user

PROFILE = YandexUser(id="1234567", email="specialist@example.com", display_name="Иван")


@pytest.fixture
def settings() -> Settings:
    return Settings(
        app_env="development",
        app_base_url="http://localhost:3000",
        yandex_oauth_client_id="test-client",
        yandex_oauth_client_secret="test-secret",
    )


@pytest.fixture
async def client(session: AsyncSession, settings: Settings) -> AsyncIterator[AsyncClient]:
    app = create_app()

    async def override_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_settings] = lambda: settings

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False
    ) as ac:
        yield ac


@pytest.fixture
async def user(
    session: AsyncSession, two_organizations: tuple[Organization, Organization]
) -> User:
    org, _ = two_organizations
    created = await make_user(session, org, "specialist@example.com")
    await session.commit()
    return created


async def login(client: AsyncClient) -> None:
    start = await client.get("/api/v1/auth/login")
    state = start.cookies[STATE_COOKIE]

    with (
        patch("ads_os.api.v1.auth.yandex_id.exchange_code", return_value="ya-token"),
        patch("ads_os.api.v1.auth.yandex_id.fetch_user", return_value=PROFILE),
    ):
        await client.get(f"/api/v1/auth/callback?code=abc&state={state}")


class TestОписаниеУстройства:
    def test_браузер_и_система(self) -> None:
        agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537"
        assert describe_device(agent) == "Chrome на Windows"

    def test_яндекс_браузер_узнаётся_раньше_chrome(self) -> None:
        """Он представляется и как Chrome — важен порядок проверки."""
        agent = "Mozilla/5.0 (Windows NT 10.0) YaBrowser/24.1 Chrome/120 Safari/537"
        assert describe_device(agent) == "Яндекс Браузер на Windows"

    def test_без_заголовка_честная_заглушка(self) -> None:
        assert describe_device(None) == "Неизвестное устройство"
        assert describe_device("") == "Неизвестное устройство"

    def test_неизвестный_агент_не_ломается(self) -> None:
        assert describe_device("curl/8.5.0") == "Неизвестное устройство"


class TestСписок:
    async def test_текущий_вход_помечен(
        self, client: AsyncClient, session: AsyncSession, user: User
    ) -> None:
        await login(client)

        body = (await client.get("/api/v1/auth/sessions")).json()

        assert body["total"] == 1
        assert body["items"][0]["is_current"] is True

    async def test_видны_все_свои_входы(
        self, client: AsyncClient, session: AsyncSession, user: User
    ) -> None:
        await issue_session(session, user, ttl=timedelta(days=1), user_agent="curl/8")
        await session.commit()
        await login(client)

        body = (await client.get("/api/v1/auth/sessions")).json()

        assert body["total"] == 2
        assert sum(1 for item in body["items"] if item["is_current"]) == 1

    async def test_завершённые_входы_не_показываются(
        self, client: AsyncClient, session: AsyncSession, user: User
    ) -> None:
        issued = await issue_session(session, user, ttl=timedelta(days=1))
        issued.session.revoked_at = issued.session.created_at
        await session.commit()
        await login(client)

        assert (await client.get("/api/v1/auth/sessions")).json()["total"] == 1

    async def test_истёкшие_входы_не_показываются(
        self, client: AsyncClient, session: AsyncSession, user: User
    ) -> None:
        await issue_session(session, user, ttl=-timedelta(seconds=1))
        await session.commit()
        await login(client)

        assert (await client.get("/api/v1/auth/sessions")).json()["total"] == 1

    async def test_чужие_входы_не_видны(
        self,
        client: AsyncClient,
        session: AsyncSession,
        user: User,
        two_organizations: tuple[Organization, Organization],
    ) -> None:
        """Список личный: даже владелец не разглядывает устройства коллег."""
        org, _ = two_organizations
        colleague = await make_user(session, org, "colleague@example.com")
        await issue_session(session, colleague, ttl=timedelta(days=1))
        await session.commit()
        await login(client)

        assert (await client.get("/api/v1/auth/sessions")).json()["total"] == 1

    async def test_без_входа_список_недоступен(self, client: AsyncClient) -> None:
        assert (await client.get("/api/v1/auth/sessions")).status_code == 401


class TestЗавершение:
    async def test_чужое_устройство_завершается(
        self, client: AsyncClient, session: AsyncSession, user: User
    ) -> None:
        other = await issue_session(session, user, ttl=timedelta(days=1))
        await session.commit()
        await login(client)

        response = await client.delete(f"/api/v1/auth/sessions/{other.session.id}")

        assert response.status_code == 204
        assert await resolve_session(session, other.token) is None

    async def test_текущий_вход_так_не_завершить(
        self, client: AsyncClient, session: AsyncSession, user: User
    ) -> None:
        """Для выхода есть отдельная кнопка — она ещё и убирает куку."""
        await login(client)
        current = (await client.get("/api/v1/auth/sessions")).json()["items"][0]["id"]

        response = await client.delete(f"/api/v1/auth/sessions/{current}")

        assert response.status_code == 404
        assert (await client.get("/api/v1/auth/sessions")).status_code == 200

    async def test_чужую_сессию_завершить_нельзя(
        self,
        client: AsyncClient,
        session: AsyncSession,
        user: User,
        two_organizations: tuple[Organization, Organization],
    ) -> None:
        org, _ = two_organizations
        colleague = await make_user(session, org, "colleague@example.com")
        theirs = await issue_session(session, colleague, ttl=timedelta(days=1))
        await session.commit()
        await login(client)

        response = await client.delete(f"/api/v1/auth/sessions/{theirs.session.id}")

        assert response.status_code == 404
        assert await resolve_session(session, theirs.token) is not None
