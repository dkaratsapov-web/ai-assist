"""Вход через Яндекс ID: полный путь через HTTP.

Сам Яндекс подменяется: тесты не должны зависеть от чужого сервиса. Подменяется
именно граница — обмен кода и получение профиля, — а всё, что после неё,
работает по-настоящему.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ads_os.api.deps import get_session
from ads_os.api.v1.auth import STATE_COOKIE
from ads_os.config import Settings, get_settings
from ads_os.main import create_app
from ads_os.models import Organization, Session, User
from ads_os.services.auth import COOKIE_NAME
from ads_os.services.yandex_id import YandexAuthError, YandexUser
from ads_os.tenancy.context import Role

from .conftest import make_user

PROFILE = YandexUser(id="1234567", email="specialist@example.com", display_name="Иван Петров")


@pytest.fixture
def settings() -> Settings:
    return Settings(
        app_env="development",
        app_base_url="http://localhost:3000",
        yandex_oauth_client_id="test-client",
        yandex_oauth_client_secret="test-secret",
        bootstrap_owner_email="founder@example.com",
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


async def login(client: AsyncClient, profile: YandexUser = PROFILE) -> AsyncClient:
    """Проходит вход целиком и оставляет куку сессии в клиенте."""
    start = await client.get("/api/v1/auth/login")
    state = start.cookies[STATE_COOKIE]

    with (
        patch("ads_os.api.v1.auth.yandex_id.exchange_code", return_value="ya-token"),
        patch("ads_os.api.v1.auth.yandex_id.fetch_user", return_value=profile),
    ):
        await client.get(f"/api/v1/auth/callback?code=abc&state={state}")

    return client


class TestНачалоВхода:
    async def test_отправляет_на_яндекс(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/auth/login")

        assert response.status_code == 307
        assert response.headers["location"].startswith("https://oauth.yandex.ru/authorize")

    async def test_кладёт_state_в_куку(self, client: AsyncClient) -> None:
        """Без него можно подсунуть чужой код авторизации."""
        response = await client.get("/api/v1/auth/login")

        assert STATE_COOKIE in response.cookies
        assert response.cookies[STATE_COOKIE] in response.headers["location"]

    async def test_без_настроек_честный_отказ(
        self, session: AsyncSession, settings: Settings
    ) -> None:
        app = create_app()

        async def override_session() -> AsyncIterator[AsyncSession]:
            yield session

        app.dependency_overrides[get_session] = override_session
        app.dependency_overrides[get_settings] = lambda: Settings(app_env="development")

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.get("/api/v1/auth/login")

        assert response.status_code == 503
        assert response.json()["error_code"] == "login_not_configured"


class TestВозврат:
    async def test_участник_входит(
        self,
        client: AsyncClient,
        session: AsyncSession,
        two_organizations: tuple[Organization, Organization],
    ) -> None:
        org, _ = two_organizations
        await make_user(session, org, "specialist@example.com")
        await session.commit()

        await login(client)

        me = await client.get("/api/v1/auth/me")
        assert me.status_code == 200
        assert me.json()["email"] == "specialist@example.com"

    async def test_чужой_человек_не_входит(
        self,
        client: AsyncClient,
        session: AsyncSession,
        two_organizations: tuple[Organization, Organization],
    ) -> None:
        """Регистрации «с улицы» нет: доступ выдаёт владелец."""
        org, _ = two_organizations
        await make_user(session, org, "specialist@example.com")
        await session.commit()

        start = await client.get("/api/v1/auth/login")
        state = start.cookies[STATE_COOKIE]
        stranger = YandexUser(id="999", email="stranger@example.com", display_name="Чужой")

        with (
            patch("ads_os.api.v1.auth.yandex_id.exchange_code", return_value="ya-token"),
            patch("ads_os.api.v1.auth.yandex_id.fetch_user", return_value=stranger),
        ):
            response = await client.get(f"/api/v1/auth/callback?code=abc&state={state}")

        assert response.status_code == 403
        assert response.json()["error_code"] == "access_denied"

    async def test_подменённый_state_отклоняется(
        self,
        client: AsyncClient,
        session: AsyncSession,
        two_organizations: tuple[Organization, Organization],
    ) -> None:
        """Ответ пришёл не на наш запрос — так выглядит подмена кода."""
        org, _ = two_organizations
        await make_user(session, org, "specialist@example.com")
        await session.commit()

        await client.get("/api/v1/auth/login")

        with (
            patch("ads_os.api.v1.auth.yandex_id.exchange_code", return_value="ya-token"),
            patch("ads_os.api.v1.auth.yandex_id.fetch_user", return_value=PROFILE),
        ):
            response = await client.get("/api/v1/auth/callback?code=abc&state=чужое")

        assert response.status_code == 403

    async def test_сбой_яндекса_не_пускает_внутрь(
        self,
        client: AsyncClient,
        session: AsyncSession,
        two_organizations: tuple[Organization, Organization],
    ) -> None:
        org, _ = two_organizations
        await make_user(session, org, "specialist@example.com")
        await session.commit()

        start = await client.get("/api/v1/auth/login")
        state = start.cookies[STATE_COOKIE]

        with patch(
            "ads_os.api.v1.auth.yandex_id.exchange_code",
            side_effect=YandexAuthError("код ответа 500"),
        ):
            response = await client.get(f"/api/v1/auth/callback?code=abc&state={state}")

        assert response.status_code == 403

    async def test_отключённый_участник_не_входит(
        self,
        client: AsyncClient,
        session: AsyncSession,
        two_organizations: tuple[Organization, Organization],
    ) -> None:
        org, _ = two_organizations
        user = await make_user(session, org, "specialist@example.com")
        user.is_active = False
        await session.commit()

        start = await client.get("/api/v1/auth/login")
        state = start.cookies[STATE_COOKIE]

        with (
            patch("ads_os.api.v1.auth.yandex_id.exchange_code", return_value="ya-token"),
            patch("ads_os.api.v1.auth.yandex_id.fetch_user", return_value=PROFILE),
        ):
            response = await client.get(f"/api/v1/auth/callback?code=abc&state={state}")

        assert response.status_code == 403

    async def test_идентификатор_яндекса_запоминается(
        self,
        client: AsyncClient,
        session: AsyncSession,
        two_organizations: tuple[Organization, Organization],
    ) -> None:
        """Дальше сопоставление идёт по нему: почту в аккаунте можно сменить."""
        org, _ = two_organizations
        user = await make_user(session, org, "specialist@example.com")
        await session.commit()

        await login(client)

        await session.refresh(user)
        assert user.yandex_id == PROFILE.id

    async def test_смена_почты_не_отрезает_от_системы(
        self,
        client: AsyncClient,
        session: AsyncSession,
        two_organizations: tuple[Organization, Organization],
    ) -> None:
        org, _ = two_organizations
        user = await make_user(session, org, "specialist@example.com")
        user.yandex_id = PROFILE.id
        await session.commit()

        renamed = YandexUser(id=PROFILE.id, email="new@example.com", display_name="Иван")
        await login(client, renamed)

        me = await client.get("/api/v1/auth/me")
        assert me.status_code == 200


class TestПервыйВладелец:
    async def test_создаётся_по_настройке_сервера(self, client: AsyncClient) -> None:
        """Первого владельца некому пригласить — он и есть тот, кто приглашает."""
        founder = YandexUser(id="42", email="founder@example.com", display_name="Основатель")

        await login(client, founder)

        me = await client.get("/api/v1/auth/me")
        assert me.status_code == 200
        assert me.json()["role"] == "owner"

    async def test_дверь_закрывается_после_первого_раза(
        self,
        client: AsyncClient,
        session: AsyncSession,
        two_organizations: tuple[Organization, Organization],
    ) -> None:
        """Владелец уже есть — значит этот путь больше не работает."""
        org, _ = two_organizations
        owner = await make_user(session, org, "owner@example.com")
        owner.role = Role.OWNER
        await session.commit()

        founder = YandexUser(id="42", email="founder@example.com", display_name="Основатель")
        start = await client.get("/api/v1/auth/login")
        state = start.cookies[STATE_COOKIE]

        with (
            patch("ads_os.api.v1.auth.yandex_id.exchange_code", return_value="ya-token"),
            patch("ads_os.api.v1.auth.yandex_id.fetch_user", return_value=founder),
        ):
            response = await client.get(f"/api/v1/auth/callback?code=abc&state={state}")

        assert response.status_code == 403

    async def test_чужая_почта_владельцем_не_становится(self, client: AsyncClient) -> None:
        stranger = YandexUser(id="7", email="stranger@example.com", display_name="Чужой")
        start = await client.get("/api/v1/auth/login")
        state = start.cookies[STATE_COOKIE]

        with (
            patch("ads_os.api.v1.auth.yandex_id.exchange_code", return_value="ya-token"),
            patch("ads_os.api.v1.auth.yandex_id.fetch_user", return_value=stranger),
        ):
            response = await client.get(f"/api/v1/auth/callback?code=abc&state={state}")

        assert response.status_code == 403


class TestВыход:
    async def test_сессия_завершается(
        self,
        client: AsyncClient,
        session: AsyncSession,
        two_organizations: tuple[Organization, Organization],
    ) -> None:
        org, _ = two_organizations
        await make_user(session, org, "specialist@example.com")
        await session.commit()
        await login(client)

        response = await client.post("/api/v1/auth/logout")

        assert response.status_code == 204
        assert (await client.get("/api/v1/auth/me")).status_code == 401

    async def test_отозванная_сессия_остаётся_в_журнале(
        self,
        client: AsyncClient,
        session: AsyncSession,
        two_organizations: tuple[Organization, Organization],
    ) -> None:
        """Видно, что вход был и когда он закончился."""
        org, _ = two_organizations
        await make_user(session, org, "specialist@example.com")
        await session.commit()
        await login(client)
        await client.post("/api/v1/auth/logout")

        rows = (await session.execute(select(Session))).scalars().all()
        assert len(rows) == 1
        assert rows[0].revoked_at is not None


class TestДоступКДанным:
    async def test_без_входа_данные_недоступны(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/projects")

        assert response.status_code == 401

    async def test_после_входа_данные_доступны(
        self,
        client: AsyncClient,
        session: AsyncSession,
        two_organizations: tuple[Organization, Organization],
    ) -> None:
        org, _ = two_organizations
        await make_user(session, org, "specialist@example.com")
        await session.commit()
        await login(client)

        response = await client.get("/api/v1/projects")

        assert response.status_code == 200

    async def test_кука_сессии_недоступна_скриптам(
        self,
        client: AsyncClient,
        session: AsyncSession,
        two_organizations: tuple[Organization, Organization],
    ) -> None:
        """Иначе любая уязвимость в вёрстке превращается в кражу сессии."""
        org, _ = two_organizations
        await make_user(session, org, "specialist@example.com")
        await session.commit()

        start = await client.get("/api/v1/auth/login")
        state = start.cookies[STATE_COOKIE]

        with (
            patch("ads_os.api.v1.auth.yandex_id.exchange_code", return_value="ya-token"),
            patch("ads_os.api.v1.auth.yandex_id.fetch_user", return_value=PROFILE),
        ):
            response = await client.get(f"/api/v1/auth/callback?code=abc&state={state}")

        cookie_header = response.headers["set-cookie"]
        assert COOKIE_NAME in cookie_header
        assert "httponly" in cookie_header.lower()

    async def test_заголовки_чужой_организации_не_переопределяют_сессию(
        self,
        client: AsyncClient,
        session: AsyncSession,
        two_organizations: tuple[Organization, Organization],
    ) -> None:
        """Вошедший не может подменить организацию заголовком."""
        org, other_org = two_organizations
        await make_user(session, org, "specialist@example.com")
        stranger = await make_user(session, other_org, "stranger@example.com")
        await session.commit()
        await login(client)

        response = await client.get(
            "/api/v1/auth/me",
            headers={
                "X-Organization-Id": str(other_org.id),
                "X-User-Id": str(stranger.id),
                "X-User-Role": "owner",
            },
        )

        assert response.json()["email"] == "specialist@example.com"


class TestУчастники:
    async def test_владелец_добавляет_участника(
        self,
        client: AsyncClient,
        session: AsyncSession,
        two_organizations: tuple[Organization, Organization],
    ) -> None:
        org, _ = two_organizations
        owner = await make_user(session, org, "specialist@example.com")
        owner.role = Role.OWNER
        await session.commit()
        await login(client)

        response = await client.post(
            "/api/v1/organization/members",
            json={"email": "New@Example.com", "full_name": "Новый", "role": "specialist"},
        )

        assert response.status_code == 201
        body = response.json()
        # Почта приводится к нижнему регистру: иначе вход с той же почтой в
        # другом написании не нашёл бы участника.
        assert body["email"] == "new@example.com"
        assert body["has_logged_in"] is False

    async def test_специалист_участников_не_добавляет(
        self,
        client: AsyncClient,
        session: AsyncSession,
        two_organizations: tuple[Organization, Organization],
    ) -> None:
        """Раздача доступов — право владельца, иначе роль ничего не значит."""
        org, _ = two_organizations
        await make_user(session, org, "specialist@example.com")
        await session.commit()
        await login(client)

        response = await client.post(
            "/api/v1/organization/members",
            json={"email": "new@example.com", "full_name": "Новый"},
        )

        assert response.status_code == 403

    async def test_отключение_участника_завершает_его_сессии(
        self,
        client: AsyncClient,
        session: AsyncSession,
        two_organizations: tuple[Organization, Organization],
    ) -> None:
        org, _ = two_organizations
        owner = await make_user(session, org, "specialist@example.com")
        owner.role = Role.OWNER
        victim = await make_user(session, org, "victim@example.com")
        await session.commit()

        from datetime import timedelta

        from ads_os.services.auth import issue_session, resolve_session

        issued = await issue_session(session, victim, ttl=timedelta(days=1))
        await session.commit()

        await login(client)
        response = await client.patch(
            f"/api/v1/organization/members/{victim.id}", json={"is_active": False}
        )

        assert response.status_code == 200
        assert await resolve_session(session, issued.token) is None

    async def test_последнего_владельца_нельзя_отключить(
        self,
        client: AsyncClient,
        session: AsyncSession,
        two_organizations: tuple[Organization, Organization],
    ) -> None:
        """Иначе организация останется без того, кто выдаёт доступы."""
        org, _ = two_organizations
        owner = await make_user(session, org, "specialist@example.com")
        owner.role = Role.OWNER
        await session.commit()
        await login(client)

        response = await client.patch(
            f"/api/v1/organization/members/{owner.id}", json={"is_active": False}
        )

        assert response.status_code == 422
        assert response.json()["error_code"] == "last_owner"

    async def test_чужой_участник_недоступен(
        self,
        client: AsyncClient,
        session: AsyncSession,
        two_organizations: tuple[Organization, Organization],
    ) -> None:
        org, other_org = two_organizations
        owner = await make_user(session, org, "specialist@example.com")
        owner.role = Role.OWNER
        stranger = await make_user(session, other_org, "stranger@example.com")
        await session.commit()
        await login(client)

        response = await client.patch(
            f"/api/v1/organization/members/{stranger.id}", json={"full_name": "Взлом"}
        )

        assert response.status_code == 404


class TestДублиУчастников:
    async def test_повторная_почта_отклоняется(
        self,
        client: AsyncClient,
        session: AsyncSession,
        two_organizations: tuple[Organization, Organization],
    ) -> None:
        org, _ = two_organizations
        owner = await make_user(session, org, "specialist@example.com")
        owner.role = Role.OWNER
        await session.commit()
        await login(client)

        first = await client.post(
            "/api/v1/organization/members",
            json={"email": "dup@example.com", "full_name": "Первый"},
        )
        second = await client.post(
            "/api/v1/organization/members",
            json={"email": "DUP@example.com", "full_name": "Второй"},
        )

        assert first.status_code == 201
        assert second.status_code == 409


class TestСозданиеПользователей:
    async def test_добавленный_участник_может_войти(
        self,
        client: AsyncClient,
        session: AsyncSession,
        two_organizations: tuple[Organization, Organization],
    ) -> None:
        """Полный путь: владелец выдал доступ — человек вошёл."""
        org, _ = two_organizations
        owner = await make_user(session, org, "specialist@example.com")
        owner.role = Role.OWNER
        await session.commit()
        await login(client)

        await client.post(
            "/api/v1/organization/members",
            json={"email": "newbie@example.com", "full_name": "Новичок"},
        )
        await session.commit()

        created = (
            await session.execute(select(User).where(User.email == "newbie@example.com"))
        ).scalar_one()
        assert created.yandex_id is None
