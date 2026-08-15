"""Наборы минус-слов.

Проверяется то, ради чего наборы существуют: работа, сделанная в одном проекте,
переносится в следующий и при этом ничего в нём не затирает.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from ads_os.api.deps import get_session
from ads_os.main import create_app
from ads_os.models import Organization, Project, User

from .conftest import make_user

LIST = "окна пвх цена\t900\nокна пвх вакансии\t100\nокна пвх рассрочка\t80"


@pytest.fixture
async def client(session: AsyncSession) -> AsyncIterator[AsyncClient]:
    app = create_app()

    async def override() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def two_projects(
    session: AsyncSession, two_organizations: tuple[Organization, Organization]
) -> tuple[Organization, User, Project, Project]:
    org, _ = two_organizations
    user = await make_user(session, org, "s@example.com")
    first = Project(organization_id=org.id, name="Первый", created_by_id=user.id)
    second = Project(organization_id=org.id, name="Второй", created_by_id=user.id)
    session.add_all([first, second])
    await session.commit()
    return org, user, first, second


def headers(org: Organization, user: User) -> dict[str, str]:
    return {
        "X-Organization-Id": str(org.id),
        "X-User-Id": str(user.id),
        "X-User-Role": "specialist",
    }


class TestСохранение:
    async def test_набор_собирается_из_готового_проекта(
        self, client: AsyncClient, two_projects: tuple[Organization, User, Project, Project]
    ) -> None:
        """Набор рождается из работы, а не из желания завести набор."""
        org, user, first, _ = two_projects
        for word in ("вакансии", "бесплатно"):
            await client.post(
                f"/api/v1/projects/{first.id}/minus-words",
                json={"word": word},
                headers=headers(org, user),
            )

        body = (
            await client.post(
                "/api/v1/minus-word-sets",
                json={"name": "Окна", "source_project_id": str(first.id)},
                headers=headers(org, user),
            )
        ).json()

        assert sorted(body["words"]) == ["бесплатно", "вакансии"]

    async def test_повторы_и_минусы_в_записи_убираются(
        self, client: AsyncClient, two_projects: tuple[Organization, User, Project, Project]
    ) -> None:
        """«-Вакансии» и «вакансии» — одно слово, записанное по-разному."""
        org, user, _, _ = two_projects

        body = (
            await client.post(
                "/api/v1/minus-word-sets",
                json={"name": "Общий", "words": ["-Вакансии", "вакансии", " Работа "]},
                headers=headers(org, user),
            )
        ).json()

        assert body["words"] == ["вакансии", "работа"]

    async def test_пустой_набор_не_сохраняется(
        self, client: AsyncClient, two_projects: tuple[Organization, User, Project, Project]
    ) -> None:
        org, user, first, _ = two_projects

        response = await client.post(
            "/api/v1/minus-word-sets",
            json={"name": "Пустой", "source_project_id": str(first.id)},
            headers=headers(org, user),
        )

        assert response.status_code == 422

    async def test_повторное_название_отклоняется(
        self, client: AsyncClient, two_projects: tuple[Organization, User, Project, Project]
    ) -> None:
        org, user, _, _ = two_projects
        payload = {"name": "Окна", "words": ["вакансии"]}
        await client.post("/api/v1/minus-word-sets", json=payload, headers=headers(org, user))

        response = await client.post(
            "/api/v1/minus-word-sets", json=payload, headers=headers(org, user)
        )

        assert response.status_code == 409


class TestПрименение:
    async def test_набор_переносит_работу_в_другой_проект(
        self, client: AsyncClient, two_projects: tuple[Organization, User, Project, Project]
    ) -> None:
        org, user, _, second = two_projects
        created = (
            await client.post(
                "/api/v1/minus-word-sets",
                json={"name": "Окна", "words": ["вакансии", "рассрочка"]},
                headers=headers(org, user),
            )
        ).json()
        await client.post(
            f"/api/v1/projects/{second.id}/keywords/import",
            json={"text": LIST},
            headers=headers(org, user),
        )

        result = (
            await client.post(
                f"/api/v1/projects/{second.id}/minus-words/apply/{created['id']}",
                headers=headers(org, user),
            )
        ).json()

        assert result["added"] == 2

        # Ядро перепроверено: набор, не изменивший ни одной фразы, выглядел бы
        # применённым, хотя не сделал ничего.
        body = (
            await client.get(
                f"/api/v1/projects/{second.id}/keywords?intent=irrelevant",
                headers=headers(org, user),
            )
        ).json()
        assert any("рассрочка" in item["phrase"] for item in body["items"])

    async def test_уже_имеющиеся_слова_считаются_отдельно(
        self, client: AsyncClient, two_projects: tuple[Organization, User, Project, Project]
    ) -> None:
        """«Добавлено 0» без этого числа читается как сбой."""
        org, user, _, second = two_projects
        created = (
            await client.post(
                "/api/v1/minus-word-sets",
                json={"name": "Окна", "words": ["вакансии"]},
                headers=headers(org, user),
            )
        ).json()
        await client.post(
            f"/api/v1/projects/{second.id}/minus-words",
            json={"word": "вакансии"},
            headers=headers(org, user),
        )

        result = (
            await client.post(
                f"/api/v1/projects/{second.id}/minus-words/apply/{created['id']}",
                headers=headers(org, user),
            )
        ).json()

        assert result["added"] == 0
        assert result["already_present"] == 1

    async def test_свои_минус_слова_проекта_не_затираются(
        self, client: AsyncClient, two_projects: tuple[Organization, User, Project, Project]
    ) -> None:
        """Набор — заготовка, а не источник правды о проекте."""
        org, user, _, second = two_projects
        await client.post(
            f"/api/v1/projects/{second.id}/minus-words",
            json={"word": "своё-слово"},
            headers=headers(org, user),
        )
        created = (
            await client.post(
                "/api/v1/minus-word-sets",
                json={"name": "Окна", "words": ["вакансии"]},
                headers=headers(org, user),
            )
        ).json()

        await client.post(
            f"/api/v1/projects/{second.id}/minus-words/apply/{created['id']}",
            headers=headers(org, user),
        )

        body = (
            await client.get(
                f"/api/v1/projects/{second.id}/minus-words", headers=headers(org, user)
            )
        ).json()

        assert {item["word"] for item in body["items"]} == {"своё-слово", "вакансии"}

    async def test_удаление_набора_не_трогает_проекты(
        self, client: AsyncClient, two_projects: tuple[Organization, User, Project, Project]
    ) -> None:
        """Слова стали частью работы над проектом, который никто не открывал."""
        org, user, _, second = two_projects
        created = (
            await client.post(
                "/api/v1/minus-word-sets",
                json={"name": "Окна", "words": ["вакансии"]},
                headers=headers(org, user),
            )
        ).json()
        await client.post(
            f"/api/v1/projects/{second.id}/minus-words/apply/{created['id']}",
            headers=headers(org, user),
        )

        await client.delete(
            f"/api/v1/minus-word-sets/{created['id']}", headers=headers(org, user)
        )

        body = (
            await client.get(
                f"/api/v1/projects/{second.id}/minus-words", headers=headers(org, user)
            )
        ).json()
        assert body["total"] == 1

    async def test_чужие_наборы_недоступны(
        self,
        client: AsyncClient,
        session: AsyncSession,
        two_projects: tuple[Organization, User, Project, Project],
        two_organizations: tuple[Organization, Organization],
    ) -> None:
        org, user, _, _ = two_projects
        _, other_org = two_organizations
        other_user = await make_user(session, other_org, "other@example.com")
        await session.commit()
        await client.post(
            "/api/v1/minus-word-sets",
            json={"name": "Окна", "words": ["вакансии"]},
            headers=headers(org, user),
        )

        body = (
            await client.get("/api/v1/minus-word-sets", headers=headers(other_org, other_user))
        ).json()

        assert body["total"] == 0
