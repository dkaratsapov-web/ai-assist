"""Семантика через API: импорт, ручные правки, минус-слова."""

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

LIST = """\
купить пластиковые окна\t5000
пластиковые окна цена\t3000
пластиковых окон недорого\t1000
установка окон вакансии\t400
пластиковые окна своими руками\t300
как выбрать пластиковые окна\t200
"""


@pytest.fixture
async def client(session: AsyncSession) -> AsyncIterator[AsyncClient]:
    app = create_app()

    async def override() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def project(
    session: AsyncSession, two_organizations: tuple[Organization, Organization]
) -> tuple[Organization, User, Project]:
    org, _ = two_organizations
    user = await make_user(session, org, "specialist@example.com")
    row = Project(organization_id=org.id, name="Окна Тверь", created_by_id=user.id)
    session.add(row)
    await session.commit()
    return org, user, row


def headers(org: Organization, user: User) -> dict[str, str]:
    return {
        "X-Organization-Id": str(org.id),
        "X-User-Id": str(user.id),
        "X-User-Role": "specialist",
    }


class TestИмпорт:
    async def test_список_разбирается_и_считается(
        self, client: AsyncClient, project: tuple[Organization, User, Project]
    ) -> None:
        org, user, row = project

        body = (
            await client.post(
                f"/api/v1/projects/{row.id}/keywords/import",
                json={"text": LIST},
                headers=headers(org, user),
            )
        ).json()

        assert body["added"] == 6
        assert body["irrelevant"] == 2  # вакансии и «своими руками»
        assert body["informational"] == 1  # «как выбрать»
        assert body["commercial"] == 3

    async def test_повторный_импорт_не_удваивает_ядро(
        self, client: AsyncClient, project: tuple[Organization, User, Project]
    ) -> None:
        org, user, row = project
        for _ in range(2):
            await client.post(
                f"/api/v1/projects/{row.id}/keywords/import",
                json={"text": LIST},
                headers=headers(org, user),
            )

        body = (
            await client.get(
                f"/api/v1/projects/{row.id}/keywords", headers=headers(org, user)
            )
        ).json()

        assert body["total"] == 6

    async def test_ручное_решение_переживает_импорт(
        self, client: AsyncClient, project: tuple[Organization, User, Project]
    ) -> None:
        """Иначе правка терялась бы при каждой загрузке."""
        org, user, row = project
        await client.post(
            f"/api/v1/projects/{row.id}/keywords/import",
            json={"text": LIST},
            headers=headers(org, user),
        )

        items = (
            await client.get(
                f"/api/v1/projects/{row.id}/keywords?intent=informational",
                headers=headers(org, user),
            )
        ).json()["items"]

        await client.patch(
            f"/api/v1/projects/{row.id}/keywords/{items[0]['id']}",
            json={"intent": "commercial"},
            headers=headers(org, user),
        )

        await client.post(
            f"/api/v1/projects/{row.id}/keywords/import",
            json={"text": LIST},
            headers=headers(org, user),
        )

        after = (
            await client.get(
                f"/api/v1/projects/{row.id}/keywords", headers=headers(org, user)
            )
        ).json()["items"]
        changed = next(item for item in after if item["id"] == items[0]["id"])

        assert changed["intent"] == "commercial"
        assert changed["is_manual"] is True

    async def test_чужой_проект_недоступен(
        self,
        client: AsyncClient,
        session: AsyncSession,
        project: tuple[Organization, User, Project],
        two_organizations: tuple[Organization, Organization],
    ) -> None:
        _, _, row = project
        _, other_org = two_organizations
        other_user = await make_user(session, other_org, "other@example.com")
        await session.commit()

        response = await client.post(
            f"/api/v1/projects/{row.id}/keywords/import",
            json={"text": LIST},
            headers=headers(other_org, other_user),
        )

        assert response.status_code == 404


class TestГруппы:
    async def test_нецелевые_в_группы_не_попадают(
        self, client: AsyncClient, project: tuple[Organization, User, Project]
    ) -> None:
        """Они существуют, чтобы по ним не показываться."""
        org, user, row = project
        await client.post(
            f"/api/v1/projects/{row.id}/keywords/import",
            json={"text": LIST},
            headers=headers(org, user),
        )

        body = (
            await client.get(
                f"/api/v1/projects/{row.id}/keywords/clusters", headers=headers(org, user)
            )
        ).json()

        collected = sum(item["phrases"] for item in body["items"])
        assert collected == 4  # шесть минус два нецелевых


class TestМинусСлова:
    async def test_добавление_перепроверяет_ядро(
        self, client: AsyncClient, project: tuple[Organization, User, Project]
    ) -> None:
        """Минус-слово, не изменившее ни одной фразы, — решение без последствий."""
        org, user, row = project
        await client.post(
            f"/api/v1/projects/{row.id}/keywords/import",
            json={"text": LIST},
            headers=headers(org, user),
        )

        await client.post(
            f"/api/v1/projects/{row.id}/minus-words",
            json={"word": "недорого"},
            headers=headers(org, user),
        )

        body = (
            await client.get(
                f"/api/v1/projects/{row.id}/keywords?intent=irrelevant",
                headers=headers(org, user),
            )
        ).json()

        assert any("недорого" in item["phrase"] for item in body["items"])

    async def test_удаление_возвращает_фразы(
        self, client: AsyncClient, project: tuple[Organization, User, Project]
    ) -> None:
        org, user, row = project
        await client.post(
            f"/api/v1/projects/{row.id}/keywords/import",
            json={"text": LIST},
            headers=headers(org, user),
        )
        created = (
            await client.post(
                f"/api/v1/projects/{row.id}/minus-words",
                json={"word": "недорого"},
                headers=headers(org, user),
            )
        ).json()

        await client.delete(
            f"/api/v1/projects/{row.id}/minus-words/{created['id']}",
            headers=headers(org, user),
        )

        body = (
            await client.get(
                f"/api/v1/projects/{row.id}/keywords?intent=irrelevant",
                headers=headers(org, user),
            )
        ).json()

        assert not any("недорого" in item["phrase"] for item in body["items"])

    async def test_добавленное_не_предлагается_повторно(
        self, client: AsyncClient, project: tuple[Organization, User, Project]
    ) -> None:
        """Список предложений — это список дел, а не отчёт о сделанном."""
        org, user, row = project
        await client.post(
            f"/api/v1/projects/{row.id}/keywords/import",
            json={"text": LIST},
            headers=headers(org, user),
        )
        await client.post(
            f"/api/v1/projects/{row.id}/minus-words",
            json={"word": "вакансии"},
            headers=headers(org, user),
        )

        body = (
            await client.get(
                f"/api/v1/projects/{row.id}/minus-words", headers=headers(org, user)
            )
        ).json()

        assert "вакансии" not in {s["word"] for s in body["suggestions"]}


class TestЧерновикиОбъявлений:
    async def test_без_аудита_тексты_не_выдумываются(
        self, client: AsyncClient, project: tuple[Organization, User, Project]
    ) -> None:
        """Брать текст неоткуда — и это надо сказать, а не сочинить."""
        org, user, row = project
        await client.post(
            f"/api/v1/projects/{row.id}/keywords/import",
            json={"text": LIST},
            headers=headers(org, user),
        )

        body = (
            await client.get(f"/api/v1/projects/{row.id}/ads", headers=headers(org, user))
        ).json()

        assert body["source_note"]
        assert "аудит" in body["source_note"].lower()
        assert all(item["text"] == "" for item in body["items"])

    async def test_черновик_собирается_из_фрагментов_страницы(
        self,
        client: AsyncClient,
        session: AsyncSession,
        project: tuple[Organization, User, Project],
    ) -> None:
        org, user, row = project
        session.add(
            SiteAudit(
                organization_id=org.id,
                project_id=row.id,
                url="https://example.com/",
                status=ModuleStatus.COMPLETED,
                score=90,
                categories=[],
                issues=[],
                selling_points=["Замер бесплатно", "Окно от 12 900 ₽", "Гарантия 5 лет"],
            )
        )
        await session.commit()

        await client.post(
            f"/api/v1/projects/{row.id}/keywords/import",
            json={"text": LIST},
            headers=headers(org, user),
        )

        body = (
            await client.get(f"/api/v1/projects/{row.id}/ads", headers=headers(org, user))
        ).json()

        assert body["source_note"] is None
        assert body["total"] > 0
        first = body["items"][0]
        assert "Замер бесплатно" in first["text"]
        assert first["title"]

    async def test_остаток_не_превращается_в_объявление(
        self,
        client: AsyncClient,
        session: AsyncSession,
        project: tuple[Organization, User, Project],
    ) -> None:
        """Фразы без группы — это не группа под объявление."""
        org, user, row = project
        await client.post(
            f"/api/v1/projects/{row.id}/keywords/import",
            json={"text": LIST},
            headers=headers(org, user),
        )

        body = (
            await client.get(f"/api/v1/projects/{row.id}/ads", headers=headers(org, user))
        ).json()

        assert all(item["cluster"] != "Остальные фразы" for item in body["items"])

    async def test_чужие_черновики_недоступны(
        self,
        client: AsyncClient,
        session: AsyncSession,
        project: tuple[Organization, User, Project],
        two_organizations: tuple[Organization, Organization],
    ) -> None:
        _, _, row = project
        _, other_org = two_organizations
        other_user = await make_user(session, other_org, "other@example.com")
        await session.commit()

        response = await client.get(
            f"/api/v1/projects/{row.id}/ads", headers=headers(other_org, other_user)
        )

        assert response.status_code == 404


class TestВыгрузкаКампании:
    """Единственный способ дойти до реального запуска без доступа к API."""

    async def test_выгрузка_содержит_фразы_и_объявления(
        self,
        client: AsyncClient,
        session: AsyncSession,
        project: tuple[Organization, User, Project],
    ) -> None:
        org, user, row = project
        row.website_url = "https://okna.ru/"
        session.add(
            SiteAudit(
                organization_id=org.id,
                project_id=row.id,
                url="https://okna.ru/",
                status=ModuleStatus.COMPLETED,
                score=90,
                categories=[],
                issues=[],
                selling_points=["Замер бесплатно", "Гарантия 5 лет"],
            )
        )
        await session.commit()

        await client.post(
            f"/api/v1/projects/{row.id}/keywords/import",
            json={"text": LIST},
            headers=headers(org, user),
        )
        await client.post(
            f"/api/v1/projects/{row.id}/minus-words",
            json={"word": "вакансии"},
            headers=headers(org, user),
        )

        response = await client.get(
            f"/api/v1/projects/{row.id}/campaign/export.csv", headers=headers(org, user)
        )

        assert response.status_code == 200
        body = response.text
        assert "Ключевая фраза" in body
        assert "купить пластиковые окна" in body
        assert "Замер бесплатно" in body
        assert "-вакансии" in body

    async def test_файл_открывается_в_excel(
        self,
        client: AsyncClient,
        project: tuple[Organization, User, Project],
    ) -> None:
        """Без метки кодировки Excel показывает русский текст крякозябрами."""
        org, user, row = project
        await client.post(
            f"/api/v1/projects/{row.id}/keywords/import",
            json={"text": LIST},
            headers=headers(org, user),
        )

        response = await client.get(
            f"/api/v1/projects/{row.id}/campaign/export.csv", headers=headers(org, user)
        )

        assert response.content.startswith(b"\xef\xbb\xbf")
        # Точка с запятой: с запятой Excel разносит по столбцам «12 900,00».
        assert ";" in response.text.splitlines()[0]

    async def test_нецелевые_фразы_в_выгрузку_не_попадают(
        self,
        client: AsyncClient,
        project: tuple[Organization, User, Project],
    ) -> None:
        org, user, row = project
        await client.post(
            f"/api/v1/projects/{row.id}/keywords/import",
            json={"text": LIST},
            headers=headers(org, user),
        )

        body = (
            await client.get(
                f"/api/v1/projects/{row.id}/campaign/export.csv", headers=headers(org, user)
            )
        ).text

        assert "вакансии" not in body.replace("-вакансии", "")

    async def test_замечания_не_отсеивают_строки(
        self,
        client: AsyncClient,
        project: tuple[Organization, User, Project],
    ) -> None:
        """Молча выброшенная группа обнаружилась бы уже в Директе."""
        org, user, row = project
        await client.post(
            f"/api/v1/projects/{row.id}/keywords/import",
            json={"text": LIST},
            headers=headers(org, user),
        )

        body = (
            await client.get(
                f"/api/v1/projects/{row.id}/campaign/export.csv", headers=headers(org, user)
            )
        ).text

        # Аудита нет, поэтому текст собрать не из чего — но фразы всё равно
        # выгружены, а причина указана в отдельном столбце.
        assert "купить пластиковые окна" in body
        assert "вручную" in body

    async def test_чужая_кампания_недоступна(
        self,
        client: AsyncClient,
        session: AsyncSession,
        project: tuple[Organization, User, Project],
        two_organizations: tuple[Organization, Organization],
    ) -> None:
        _, _, row = project
        _, other_org = two_organizations
        other_user = await make_user(session, other_org, "other@example.com")
        await session.commit()

        response = await client.get(
            f"/api/v1/projects/{row.id}/campaign/export.csv",
            headers=headers(other_org, other_user),
        )

        assert response.status_code == 404
