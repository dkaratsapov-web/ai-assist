"""Редактирование проекта и прогресс по шагам."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from ads_os.api.deps import get_session
from ads_os.main import create_app
from ads_os.models import Organization, Project, SiteAudit, User
from ads_os.models.audit import ModuleStatus

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
async def project_ctx(
    session: AsyncSession, two_organizations: tuple[Organization, Organization]
) -> tuple[Organization, User, Project]:
    org, _ = two_organizations
    user = await make_user(session, org, "specialist@example.com")
    project = Project(organization_id=org.id, name="Новый проект", created_by_id=user.id)
    session.add(project)
    await session.commit()
    return org, user, project


def headers(org: Organization, user: User) -> dict[str, str]:
    return {
        "X-Organization-Id": str(org.id),
        "X-User-Id": str(user.id),
        "X-User-Role": "specialist",
    }


class TestРедактирование:
    async def test_адрес_сайта_добавляется(
        self, client: AsyncClient, project_ctx: tuple[Organization, User, Project]
    ) -> None:
        """Без этого нельзя запустить аудит уже созданного проекта."""
        org, user, project = project_ctx

        response = await client.patch(
            f"/api/v1/projects/{project.id}",
            headers=headers(org, user),
            json={"website_url": "https://example.com/"},
        )

        assert response.status_code == 200
        assert response.json()["website_url"] == "https://example.com/"

    async def test_непереданные_поля_не_стираются(
        self, client: AsyncClient, project_ctx: tuple[Organization, User, Project]
    ) -> None:
        """Частичное обновление не должно обнулять остальное."""
        org, user, project = project_ctx

        await client.patch(
            f"/api/v1/projects/{project.id}",
            headers=headers(org, user),
            json={"website_url": "https://example.com/", "primary_region": "Тверь"},
        )
        response = await client.patch(
            f"/api/v1/projects/{project.id}",
            headers=headers(org, user),
            json={"name": "Переименован"},
        )

        body = response.json()
        assert body["name"] == "Переименован"
        assert body["website_url"] == "https://example.com/"
        assert body["primary_region"] == "Тверь"

    async def test_версия_растёт(
        self, client: AsyncClient, project_ctx: tuple[Organization, User, Project]
    ) -> None:
        org, user, project = project_ctx
        before = project.version

        response = await client.patch(
            f"/api/v1/projects/{project.id}",
            headers=headers(org, user),
            json={"name": "Другое имя"},
        )

        assert response.json()["version"] == before + 1

    async def test_запись_поверх_чужого_изменения_отклоняется(
        self, client: AsyncClient, project_ctx: tuple[Organization, User, Project]
    ) -> None:
        """Один и тот же проект правят и в вебе, и в боте (v0.4 §100)."""
        org, user, project = project_ctx
        stale_version = project.version

        await client.patch(
            f"/api/v1/projects/{project.id}",
            headers=headers(org, user),
            json={"name": "Изменено первым"},
        )

        response = await client.patch(
            f"/api/v1/projects/{project.id}",
            headers=headers(org, user),
            json={"name": "Изменено вторым", "expected_version": stale_version},
        )

        assert response.status_code == 409
        assert response.json()["details"]["expected_version"] == stale_version

    async def test_чужой_проект_не_редактируется(
        self,
        client: AsyncClient,
        session: AsyncSession,
        project_ctx: tuple[Organization, User, Project],
        two_organizations: tuple[Organization, Organization],
    ) -> None:
        """Чужой объект отвечает 404, а не 403: существование — тоже данные."""
        _, other_org = two_organizations
        other_user = await make_user(session, other_org, "other@example.com")
        await session.commit()
        _, _, project = project_ctx

        response = await client.patch(
            f"/api/v1/projects/{project.id}",
            headers=headers(other_org, other_user),
            json={"name": "Захвачено"},
        )

        assert response.status_code == 404


class TestПрогресс:
    async def test_у_нового_проекта_сделан_только_онбординг(
        self, client: AsyncClient, project_ctx: tuple[Organization, User, Project]
    ) -> None:
        org, user, project = project_ctx

        response = await client.get(
            f"/api/v1/projects/{project.id}/progress", headers=headers(org, user)
        )

        body = response.json()
        assert response.status_code == 200
        assert body["total_count"] == 10
        assert body["completed_count"] == 1
        assert body["current"] == "research"
        assert body["next_action"]

    async def test_завершённый_аудит_закрывает_исследование(
        self,
        client: AsyncClient,
        session: AsyncSession,
        project_ctx: tuple[Organization, User, Project],
    ) -> None:
        org, user, project = project_ctx
        project.website_url = "https://example.com/"
        session.add(
            SiteAudit(
                organization_id=org.id,
                project_id=project.id,
                url="https://example.com/",
                status=ModuleStatus.COMPLETED,
                score=82,
                categories=[],
                issues=[],
            )
        )
        await session.commit()

        response = await client.get(
            f"/api/v1/projects/{project.id}/progress", headers=headers(org, user)
        )

        body = response.json()
        research = next(s for s in body["steps"] if s["key"] == "research")
        assert research["state"] == "completed"
        assert body["current"] == "economics"

    async def test_критические_находки_блокируют_запуск(
        self,
        client: AsyncClient,
        session: AsyncSession,
        project_ctx: tuple[Organization, User, Project],
    ) -> None:
        """Прогресс обязан показывать запрет, а не молчать о нём (v0.3 §15)."""
        org, user, project = project_ctx
        project.website_url = "https://example.com/"
        session.add(
            SiteAudit(
                organization_id=org.id,
                project_id=project.id,
                url="https://example.com/",
                status=ModuleStatus.COMPLETED,
                score=35,
                categories=[],
                issues=[
                    {
                        "category": "tracking",
                        "severity": "critical",
                        "title": "Счётчик Метрики не найден",
                        "action": "Установите счётчик",
                    }
                ],
            )
        )
        await session.commit()

        response = await client.get(
            f"/api/v1/projects/{project.id}/progress", headers=headers(org, user)
        )

        launch = next(s for s in response.json()["steps"] if s["key"] == "launch")
        assert launch["state"] == "blocked"
        assert "критические" in launch["hint"]

    async def test_прогресс_чужого_проекта_недоступен(
        self,
        client: AsyncClient,
        session: AsyncSession,
        project_ctx: tuple[Organization, User, Project],
        two_organizations: tuple[Organization, Organization],
    ) -> None:
        _, other_org = two_organizations
        other_user = await make_user(session, other_org, "other2@example.com")
        await session.commit()
        _, _, project = project_ctx

        response = await client.get(
            f"/api/v1/projects/{project.id}/progress", headers=headers(other_org, other_user)
        )

        assert response.status_code == 404

    async def test_аудит_соседнего_проекта_не_влияет(
        self,
        client: AsyncClient,
        session: AsyncSession,
        project_ctx: tuple[Organization, User, Project],
    ) -> None:
        """Прогресс считается по своему проекту, а не по организации целиком."""
        org, user, project = project_ctx
        neighbour = Project(organization_id=org.id, name="Соседний", created_by_id=user.id)
        session.add(neighbour)
        await session.flush()
        session.add(
            SiteAudit(
                organization_id=org.id,
                project_id=neighbour.id,
                url="https://neighbour.example/",
                status=ModuleStatus.COMPLETED,
                categories=[],
                issues=[],
            )
        )
        project.website_url = "https://example.com/"
        await session.commit()

        response = await client.get(
            f"/api/v1/projects/{project.id}/progress", headers=headers(org, user)
        )

        research = next(s for s in response.json()["steps"] if s["key"] == "research")
        assert research["state"] == "active"
