"""Организация и удаление проекта."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from ads_os.api.deps import get_session
from ads_os.main import create_app
from ads_os.models import Organization, OrganizationPlan, Project, User

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
    user = await make_user(session, org, "owner@example.com")
    await session.commit()
    return org, user


def headers(org: Organization, user: User) -> dict[str, str]:
    return {
        "X-Organization-Id": str(org.id),
        "X-User-Id": str(user.id),
        "X-User-Role": "specialist",
    }


class TestОрганизация:
    async def test_возвращается_своя_организация(
        self, client: AsyncClient, org_ctx: tuple[Organization, User]
    ) -> None:
        org, user = org_ctx

        response = await client.get("/api/v1/organization", headers=headers(org, user))

        body = response.json()
        assert response.status_code == 200
        assert body["id"] == str(org.id)
        assert body["name"] == org.name

    async def test_режим_стенда_виден_явно(
        self, client: AsyncClient, org_ctx: tuple[Organization, User]
    ) -> None:
        """На заглушках результаты не являются выводами настоящей модели."""
        org, user = org_ctx

        body = (await client.get("/api/v1/organization", headers=headers(org, user))).json()

        assert body["ai_provider"] == "stub"
        assert body["ad_platform_adapter"] == "mock"

    async def test_участники_перечислены(
        self,
        client: AsyncClient,
        session: AsyncSession,
        org_ctx: tuple[Organization, User],
    ) -> None:
        org, user = org_ctx
        await make_user(session, org, "second@example.com")
        await session.commit()

        body = (await client.get("/api/v1/organization", headers=headers(org, user))).json()

        emails = {m["email"] for m in body["members"]}
        assert emails == {"owner@example.com", "second@example.com"}

    async def test_чужие_участники_не_видны(
        self,
        client: AsyncClient,
        session: AsyncSession,
        two_organizations: tuple[Organization, Organization],
        org_ctx: tuple[Organization, User],
    ) -> None:
        org, user = org_ctx
        _, other_org = two_organizations
        await make_user(session, other_org, "stranger@example.com")
        await session.commit()

        body = (await client.get("/api/v1/organization", headers=headers(org, user))).json()

        assert all(m["email"] != "stranger@example.com" for m in body["members"])

    async def test_лимиты_показываются_если_заданы(
        self,
        client: AsyncClient,
        session: AsyncSession,
        org_ctx: tuple[Organization, User],
    ) -> None:
        org, user = org_ctx
        session.add(OrganizationPlan(organization_id=org.id, max_projects=25))
        await session.commit()

        body = (await client.get("/api/v1/organization", headers=headers(org, user))).json()

        assert body["plan"]["max_projects"] == 25

    async def test_без_тарифа_поле_пустое_а_не_придуманное(
        self, client: AsyncClient, org_ctx: tuple[Organization, User]
    ) -> None:
        org, user = org_ctx

        body = (await client.get("/api/v1/organization", headers=headers(org, user))).json()

        assert body["plan"] is None

    async def test_считаются_только_живые_проекты(
        self,
        client: AsyncClient,
        session: AsyncSession,
        org_ctx: tuple[Organization, User],
    ) -> None:
        org, user = org_ctx
        session.add(Project(organization_id=org.id, name="Живой"))
        await session.commit()

        body = (await client.get("/api/v1/organization", headers=headers(org, user))).json()

        assert body["projects_count"] == 1


class TestУдалениеПроекта:
    async def test_проект_исчезает_из_списка(
        self,
        client: AsyncClient,
        session: AsyncSession,
        org_ctx: tuple[Organization, User],
    ) -> None:
        org, user = org_ctx
        project = Project(organization_id=org.id, name="На удаление")
        session.add(project)
        await session.commit()

        response = await client.delete(
            f"/api/v1/projects/{project.id}", headers=headers(org, user)
        )

        assert response.status_code == 204
        listing = await client.get("/api/v1/projects", headers=headers(org, user))
        assert listing.json()["total"] == 0

    async def test_удаление_мягкое(
        self,
        client: AsyncClient,
        session: AsyncSession,
        org_ctx: tuple[Organization, User],
    ) -> None:
        """Запись остаётся в базе: удалённый по ошибке проект можно вернуть."""
        org, user = org_ctx
        project = Project(organization_id=org.id, name="На удаление")
        session.add(project)
        await session.commit()

        await client.delete(f"/api/v1/projects/{project.id}", headers=headers(org, user))

        await session.refresh(project)
        assert project.deleted_at is not None

    async def test_удалённый_проект_недоступен_по_адресу(
        self,
        client: AsyncClient,
        session: AsyncSession,
        org_ctx: tuple[Organization, User],
    ) -> None:
        org, user = org_ctx
        project = Project(organization_id=org.id, name="На удаление")
        session.add(project)
        await session.commit()

        await client.delete(f"/api/v1/projects/{project.id}", headers=headers(org, user))
        response = await client.get(
            f"/api/v1/projects/{project.id}", headers=headers(org, user)
        )

        assert response.status_code == 404

    async def test_чужой_проект_не_удаляется(
        self,
        client: AsyncClient,
        session: AsyncSession,
        two_organizations: tuple[Organization, Organization],
        org_ctx: tuple[Organization, User],
    ) -> None:
        org, _ = org_ctx
        _, other_org = two_organizations
        other_user = await make_user(session, other_org, "other@example.com")
        project = Project(organization_id=org.id, name="Чужой для них")
        session.add(project)
        await session.commit()

        response = await client.delete(
            f"/api/v1/projects/{project.id}", headers=headers(other_org, other_user)
        )

        assert response.status_code == 404
        await session.refresh(project)
        assert project.deleted_at is None

    async def test_просмотрщик_удалять_не_может(
        self,
        client: AsyncClient,
        session: AsyncSession,
        org_ctx: tuple[Organization, User],
    ) -> None:
        """Роль viewer только читает (v0.3 §4)."""
        org, user = org_ctx
        project = Project(organization_id=org.id, name="Защищённый")
        session.add(project)
        await session.commit()

        response = await client.delete(
            f"/api/v1/projects/{project.id}",
            headers={**headers(org, user), "X-User-Role": "viewer"},
        )

        assert response.status_code == 403
        await session.refresh(project)
        assert project.deleted_at is None
