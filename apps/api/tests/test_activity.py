"""Журнал действий.

Проверяется прежде всего то, ради чего журнал существует: действия
подписываются автором, запись переживает удаление объекта, а секреты в неё не
попадают.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ads_os.api.deps import get_session
from ads_os.main import create_app
from ads_os.models import ActivityLog, Organization, Project, User
from ads_os.models.activity import ActivityAction
from ads_os.services.activity import changed_fields, record
from ads_os.tenancy.context import Role, TenantContext

from .conftest import make_user


@pytest.fixture
async def client(session: AsyncSession) -> AsyncIterator[AsyncClient]:
    app = create_app()

    async def override() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def org_ctx(
    session: AsyncSession, two_organizations: tuple[Organization, Organization]
) -> tuple[Organization, User]:
    org, _ = two_organizations
    user = await make_user(session, org, "specialist@example.com")
    await session.commit()
    return org, user


def headers(org: Organization, user: User) -> dict[str, str]:
    return {
        "X-Organization-Id": str(org.id),
        "X-User-Id": str(user.id),
        "X-User-Role": "specialist",
    }


class TestОтборИзменений:
    def test_неизменившиеся_поля_не_попадают(self) -> None:
        """Иначе каждое сохранение формы выглядело бы как правка всего сразу."""
        changes = changed_fields({"name": "Проект", "region": "Тверь"}, {"name": "Проект"})

        assert changes == {}

    def test_изменение_записывается_парой(self) -> None:
        changes = changed_fields({"name": "Старое"}, {"name": "Новое"})

        assert changes == {"name": "Старое → Новое"}

    def test_пустое_значение_называется_словом(self) -> None:
        """«None → Тверь» человек не прочитает."""
        changes = changed_fields({"region": None}, {"region": "Тверь"})

        assert changes == {"region": "пусто → Тверь"}


class TestЗащитаОтСекретов:
    async def test_поля_с_секретами_не_записываются(
        self, session: AsyncSession, org_ctx: tuple[Organization, User]
    ) -> None:
        """Журнал читают люди и живёт он дольше всего остального."""
        org, user = org_ctx
        ctx = TenantContext(
            organization_id=org.id, user_id=user.id, role=Role.OWNER, user_name="Иван"
        )

        await record(
            session,
            ctx,
            ActivityAction.PROJECT_UPDATED,
            subject="Проект",
            actor_name="Иван",
            details={"name": "Новое", "api_token": "секрет", "client_secret": "тоже"},
        )
        await session.commit()

        row = (await session.execute(select(ActivityLog))).scalar_one()
        assert row.details == {"name": "Новое"}

    async def test_длинные_значения_обрезаются(
        self, session: AsyncSession, org_ctx: tuple[Organization, User]
    ) -> None:
        org, user = org_ctx
        ctx = TenantContext(
            organization_id=org.id, user_id=user.id, role=Role.OWNER, user_name="Иван"
        )

        await record(
            session,
            ctx,
            ActivityAction.PROJECT_UPDATED,
            subject="Проект",
            actor_name="Иван",
            details={"note": "х" * 500},
        )
        await session.commit()

        row = (await session.execute(select(ActivityLog))).scalar_one()
        assert len(row.details["note"]) == 120


class TestЗаписьДействий:
    async def test_создание_проекта_записывается(
        self, client: AsyncClient, session: AsyncSession, org_ctx: tuple[Organization, User]
    ) -> None:
        org, user = org_ctx

        await client.post(
            "/api/v1/projects", headers=headers(org, user), json={"name": "Новый проект"}
        )

        row = (await session.execute(select(ActivityLog))).scalar_one()
        assert row.action is ActivityAction.PROJECT_CREATED
        assert row.subject == "Новый проект"

    async def test_изменение_записывает_что_именно_поменялось(
        self, client: AsyncClient, session: AsyncSession, org_ctx: tuple[Organization, User]
    ) -> None:
        org, user = org_ctx
        project = Project(organization_id=org.id, name="Проект")
        session.add(project)
        await session.commit()

        await client.patch(
            f"/api/v1/projects/{project.id}",
            headers=headers(org, user),
            json={"website_url": "https://example.com/"},
        )

        row = (
            await session.execute(
                select(ActivityLog).where(ActivityLog.action == ActivityAction.PROJECT_UPDATED)
            )
        ).scalar_one()
        assert "website_url" in row.details

    async def test_запись_переживает_удаление_проекта(
        self, client: AsyncClient, session: AsyncSession, org_ctx: tuple[Organization, User]
    ) -> None:
        """Название хранится копией — иначе журнал терял бы смысл при удалении."""
        org, user = org_ctx
        project = Project(organization_id=org.id, name="Обречённый")
        session.add(project)
        await session.commit()

        await client.delete(f"/api/v1/projects/{project.id}", headers=headers(org, user))

        row = (
            await session.execute(
                select(ActivityLog).where(ActivityLog.action == ActivityAction.PROJECT_DELETED)
            )
        ).scalar_one()
        assert row.subject == "Обречённый"


class TestЛента:
    async def test_новые_записи_сверху(
        self, client: AsyncClient, session: AsyncSession, org_ctx: tuple[Organization, User]
    ) -> None:
        org, user = org_ctx
        await client.post(
            "/api/v1/projects", headers=headers(org, user), json={"name": "Первый"}
        )
        await client.post(
            "/api/v1/projects", headers=headers(org, user), json={"name": "Второй"}
        )

        body = (await client.get("/api/v1/activity", headers=headers(org, user))).json()

        assert body["items"][0]["subject"] == "Второй"

    async def test_действие_подписано_готовой_фразой(
        self, client: AsyncClient, session: AsyncSession, org_ctx: tuple[Organization, User]
    ) -> None:
        org, user = org_ctx
        await client.post(
            "/api/v1/projects", headers=headers(org, user), json={"name": "Проект"}
        )

        item = (await client.get("/api/v1/activity", headers=headers(org, user))).json()[
            "items"
        ][0]

        assert item["action_label"] == "создал проект"

    async def test_фильтр_по_проекту(
        self, client: AsyncClient, session: AsyncSession, org_ctx: tuple[Organization, User]
    ) -> None:
        org, user = org_ctx
        first = (
            await client.post(
                "/api/v1/projects", headers=headers(org, user), json={"name": "Первый"}
            )
        ).json()
        await client.post(
            "/api/v1/projects", headers=headers(org, user), json={"name": "Второй"}
        )

        body = (
            await client.get(
                f"/api/v1/activity?project_id={first['id']}", headers=headers(org, user)
            )
        ).json()

        assert body["total"] == 1
        assert body["items"][0]["subject"] == "Первый"

    async def test_чужой_журнал_недоступен(
        self,
        client: AsyncClient,
        session: AsyncSession,
        org_ctx: tuple[Organization, User],
        two_organizations: tuple[Organization, Organization],
    ) -> None:
        org, user = org_ctx
        _, other_org = two_organizations
        other_user = await make_user(session, other_org, "other@example.com")
        await session.commit()
        await client.post(
            "/api/v1/projects", headers=headers(org, user), json={"name": "Мой"}
        )

        body = (
            await client.get("/api/v1/activity", headers=headers(other_org, other_user))
        ).json()

        assert body["total"] == 0

    async def test_фильтр_по_чужому_проекту_отклоняется(
        self,
        client: AsyncClient,
        session: AsyncSession,
        org_ctx: tuple[Organization, User],
        two_organizations: tuple[Organization, Organization],
    ) -> None:
        """Иначе по чужому идентификатору читалась бы чужая история."""
        org, _ = org_ctx
        _, other_org = two_organizations
        other_user = await make_user(session, other_org, "other@example.com")
        project = Project(organization_id=org.id, name="Мой")
        session.add(project)
        await session.commit()

        response = await client.get(
            f"/api/v1/activity?project_id={project.id}",
            headers=headers(other_org, other_user),
        )

        assert response.status_code == 404
