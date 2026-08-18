"""Семантика через API: импорт, ручные правки, минус-слова."""

from __future__ import annotations

import base64
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


class TestПоиск:
    async def test_находит_проект_по_части_названия(
        self, client: AsyncClient, project: tuple[Organization, User, Project]
    ) -> None:
        """Запрос с маленькой буквы находит проект с большой.

        В PostgreSQL при локали C `lower()` не понижает регистр кириллицы, и
        поиск по-русски молча не находил ничего. Локаль задаётся при создании
        базы, поэтому сравнение вынесено в Python.
        """
        org, user, _ = project

        body = (await client.get("/api/v1/search?q=окна", headers=headers(org, user))).json()

        assert [item["name"] for item in body["projects"]] == ["Окна Тверь"]

    async def test_находит_фразу_вместе_с_проектом(
        self, client: AsyncClient, project: tuple[Organization, User, Project]
    ) -> None:
        """Фраза без указания проекта не отвечает ни на один вопрос."""
        org, user, row = project
        await client.post(
            f"/api/v1/projects/{row.id}/keywords/import",
            json={"text": LIST},
            headers=headers(org, user),
        )

        body = (await client.get("/api/v1/search?q=вакансии", headers=headers(org, user))).json()

        assert body["keywords"]
        assert body["keywords"][0]["project_name"] == "Окна Тверь"

    async def test_поиск_не_ломается_о_маршрут_проекта(
        self, client: AsyncClient, project: tuple[Organization, User, Project]
    ) -> None:
        """Под префиксом /projects слово «search» приняли бы за идентификатор."""
        org, user, _ = project

        response = await client.get("/api/v1/search?q=окна", headers=headers(org, user))

        assert response.status_code == 200

    async def test_чужое_не_находится(
        self,
        client: AsyncClient,
        session: AsyncSession,
        project: tuple[Organization, User, Project],
        two_organizations: tuple[Organization, Organization],
    ) -> None:
        _, other_org = two_organizations
        other_user = await make_user(session, other_org, "other@example.com")
        await session.commit()

        body = (
            await client.get("/api/v1/search?q=окна", headers=headers(other_org, other_user))
        ).json()

        assert body["projects"] == []
        assert body["keywords"] == []

    async def test_слишком_короткий_запрос_отклоняется(
        self, client: AsyncClient, project: tuple[Organization, User, Project]
    ) -> None:
        """По одной букве находится всё, и это не поиск."""
        org, user, _ = project

        response = await client.get("/api/v1/search?q=о", headers=headers(org, user))

        assert response.status_code == 422


class TestПовторённыеРешения:
    """Словарь не знает ниши. Зато знает специалист."""

    async def test_слово_из_двух_проектов_подсказывается(
        self,
        client: AsyncClient,
        session: AsyncSession,
        project: tuple[Organization, User, Project],
    ) -> None:
        org, user, current = project
        others = [
            Project(organization_id=org.id, name=f"Проект {i}", created_by_id=user.id)
            for i in range(2)
        ]
        session.add_all(others)
        await session.commit()

        for other in others:
            await client.post(
                f"/api/v1/projects/{other.id}/minus-words",
                json={"word": "рассрочка"},
                headers=headers(org, user),
            )

        body = (
            await client.get(
                f"/api/v1/projects/{current.id}/minus-words", headers=headers(org, user)
            )
        ).json()

        assert "рассрочка" in body["learned"]

    async def test_слово_из_одного_проекта_не_подсказывается(
        self,
        client: AsyncClient,
        session: AsyncSession,
        project: tuple[Organization, User, Project],
    ) -> None:
        """На одном проекте нельзя отличить нишевое слово от разовой правки."""
        org, user, current = project
        other = Project(organization_id=org.id, name="Другой", created_by_id=user.id)
        session.add(other)
        await session.commit()

        await client.post(
            f"/api/v1/projects/{other.id}/minus-words",
            json={"word": "рассрочка"},
            headers=headers(org, user),
        )

        body = (
            await client.get(
                f"/api/v1/projects/{current.id}/minus-words", headers=headers(org, user)
            )
        ).json()

        assert body["learned"] == []

    async def test_подсказка_не_применяется_сама(
        self,
        client: AsyncClient,
        session: AsyncSession,
        project: tuple[Organization, User, Project],
    ) -> None:
        """Тихо отсечённый трафик — это то, о чём человек не просил и не узнает."""
        org, user, current = project
        others = [
            Project(organization_id=org.id, name=f"П{i}", created_by_id=user.id) for i in range(2)
        ]
        session.add_all(others)
        await session.commit()
        for other in others:
            await client.post(
                f"/api/v1/projects/{other.id}/minus-words",
                json={"word": "рассрочка"},
                headers=headers(org, user),
            )

        body = (
            await client.get(
                f"/api/v1/projects/{current.id}/minus-words", headers=headers(org, user)
            )
        ).json()

        assert "рассрочка" not in {item["word"] for item in body["items"]}

    async def test_уже_добавленное_не_подсказывается(
        self,
        client: AsyncClient,
        session: AsyncSession,
        project: tuple[Organization, User, Project],
    ) -> None:
        org, user, current = project
        others = [
            Project(organization_id=org.id, name=f"П{i}", created_by_id=user.id) for i in range(2)
        ]
        session.add_all(others)
        await session.commit()
        for other in others:
            await client.post(
                f"/api/v1/projects/{other.id}/minus-words",
                json={"word": "рассрочка"},
                headers=headers(org, user),
            )
        await client.post(
            f"/api/v1/projects/{current.id}/minus-words",
            json={"word": "рассрочка"},
            headers=headers(org, user),
        )

        body = (
            await client.get(
                f"/api/v1/projects/{current.id}/minus-words", headers=headers(org, user)
            )
        ).json()

        assert body["learned"] == []


REGION_LIST = """\
пластиковые окна тверь\t900
пластиковые окна москва\t8000
окна в московской области\t2000
окна своими руками\t300
"""


class TestЧисткаЯдра:
    """Чистка через API: что помечено, что удаляется и что остаётся."""

    async def test_чужой_город_помечается_при_импорте(
        self,
        session: AsyncSession,
        client: AsyncClient,
        project: tuple[Organization, User, Project],
    ) -> None:
        org, user, row = project
        row.primary_region = "Тверь"
        await session.commit()

        body = (
            await client.post(
                f"/api/v1/projects/{row.id}/keywords/import",
                json={"text": REGION_LIST},
                headers=headers(org, user),
            )
        ).json()

        reasons = {group["reason"]: group for group in body["cleaned"]}

        assert reasons["geo"]["phrases"] == 2
        assert reasons["diy"]["phrases"] == 1
        assert body["commercial"] == 1

    async def test_без_региона_города_не_трогаются(
        self, client: AsyncClient, project: tuple[Organization, User, Project]
    ) -> None:
        """Регион не заполнен — судить не по чему, и молчание честнее находки."""
        org, user, row = project

        body = (
            await client.post(
                f"/api/v1/projects/{row.id}/keywords/import",
                json={"text": REGION_LIST},
                headers=headers(org, user),
            )
        ).json()

        assert [group["reason"] for group in body["cleaned"]] == ["diy"]

    async def test_причина_видна_в_списке_фраз(
        self,
        session: AsyncSession,
        client: AsyncClient,
        project: tuple[Organization, User, Project],
    ) -> None:
        org, user, row = project
        row.primary_region = "Тверь"
        await session.commit()
        await client.post(
            f"/api/v1/projects/{row.id}/keywords/import",
            json={"text": REGION_LIST},
            headers=headers(org, user),
        )

        items = (
            await client.get(
                f"/api/v1/projects/{row.id}/keywords?intent=irrelevant",
                headers=headers(org, user),
            )
        ).json()["items"]
        moscow = next(item for item in items if item["phrase"] == "пластиковые окна москва")

        assert moscow["reason"] == "geo"
        assert moscow["reason_label"] == "другой город"

    async def test_перепроверка_после_смены_региона(
        self,
        session: AsyncSession,
        client: AsyncClient,
        project: tuple[Organization, User, Project],
    ) -> None:
        """Ядро загружено вчера, регион уточнён сегодня. Без перепроверки
        проект навсегда остался бы с прежней разметкой."""
        org, user, row = project
        await client.post(
            f"/api/v1/projects/{row.id}/keywords/import",
            json={"text": REGION_LIST},
            headers=headers(org, user),
        )

        row.primary_region = "Тверь"
        await session.commit()

        body = (
            await client.post(
                f"/api/v1/projects/{row.id}/keywords/recheck", headers=headers(org, user)
            )
        ).json()

        assert body["affected"] == 2
        assert body["irrelevant"] == 3

    async def test_перепроверка_не_трогает_ручные_решения(
        self, client: AsyncClient, project: tuple[Organization, User, Project]
    ) -> None:
        org, user, row = project
        await client.post(
            f"/api/v1/projects/{row.id}/keywords/import",
            json={"text": REGION_LIST},
            headers=headers(org, user),
        )
        items = (
            await client.get(
                f"/api/v1/projects/{row.id}/keywords?intent=irrelevant",
                headers=headers(org, user),
            )
        ).json()["items"]
        await client.patch(
            f"/api/v1/projects/{row.id}/keywords/{items[0]['id']}",
            json={"intent": "commercial"},
            headers=headers(org, user),
        )

        await client.post(
            f"/api/v1/projects/{row.id}/keywords/recheck", headers=headers(org, user)
        )

        after = (
            await client.get(
                f"/api/v1/projects/{row.id}/keywords", headers=headers(org, user)
            )
        ).json()["items"]
        kept = next(item for item in after if item["id"] == items[0]["id"])

        assert kept["intent"] == "commercial"

    async def test_массовое_удаление_убирает_только_нецелевые(
        self,
        session: AsyncSession,
        client: AsyncClient,
        project: tuple[Organization, User, Project],
    ) -> None:
        org, user, row = project
        row.primary_region = "Тверь"
        await session.commit()
        await client.post(
            f"/api/v1/projects/{row.id}/keywords/import",
            json={"text": REGION_LIST},
            headers=headers(org, user),
        )

        body = (
            await client.delete(
                f"/api/v1/projects/{row.id}/keywords/irrelevant", headers=headers(org, user)
            )
        ).json()

        assert body["affected"] == 3
        assert body["remaining"] == 1
        assert body["irrelevant"] == 0

    async def test_массовое_удаление_щадит_ручные_решения(
        self, client: AsyncClient, project: tuple[Organization, User, Project]
    ) -> None:
        """Кнопка «убрать мусор» не должна стирать то, что человек решил сам."""
        org, user, row = project
        await client.post(
            f"/api/v1/projects/{row.id}/keywords/import",
            json={"text": REGION_LIST},
            headers=headers(org, user),
        )
        items = (
            await client.get(
                f"/api/v1/projects/{row.id}/keywords", headers=headers(org, user)
            )
        ).json()["items"]
        target = next(item for item in items if item["phrase"] == "пластиковые окна москва")
        await client.patch(
            f"/api/v1/projects/{row.id}/keywords/{target['id']}",
            json={"intent": "irrelevant"},
            headers=headers(org, user),
        )

        await client.delete(
            f"/api/v1/projects/{row.id}/keywords/irrelevant", headers=headers(org, user)
        )

        left = (
            await client.get(
                f"/api/v1/projects/{row.id}/keywords", headers=headers(org, user)
            )
        ).json()["items"]

        assert target["id"] in {item["id"] for item in left}

    async def test_несколько_минус_слов_разом(
        self, client: AsyncClient, project: tuple[Organization, User, Project]
    ) -> None:
        org, user, row = project
        await client.post(
            f"/api/v1/projects/{row.id}/keywords/import",
            json={"text": REGION_LIST},
            headers=headers(org, user),
        )

        body = (
            await client.post(
                f"/api/v1/projects/{row.id}/minus-words/bulk",
                json={"words": ["москва", "московская", "москва"]},
                headers=headers(org, user),
            )
        ).json()

        assert {item["word"] for item in body["items"]} == {"москва", "московская"}

        items = (
            await client.get(
                f"/api/v1/projects/{row.id}/keywords?intent=irrelevant",
                headers=headers(org, user),
            )
        ).json()["items"]

        assert len(items) == 3


class TestБрифИВыгрузка:
    """Бриф, маски и приём файла."""

    async def test_пустой_бриф_масок_не_даёт(
        self, client: AsyncClient, project: tuple[Organization, User, Project]
    ) -> None:
        org, user, row = project

        body = (
            await client.get(f"/api/v1/projects/{row.id}/brief", headers=headers(org, user))
        ).json()

        assert body["masks"] == []
        assert len(body["steps"]) >= 4
        assert body["why_manual"]

    async def test_бриф_сохраняется_и_даёт_маски(
        self,
        session: AsyncSession,
        client: AsyncClient,
        project: tuple[Organization, User, Project],
    ) -> None:
        org, user, row = project
        row.primary_region = "Тверь"
        await session.commit()

        body = (
            await client.put(
                f"/api/v1/projects/{row.id}/brief",
                json={
                    "sells": "пластиковые окна",
                    "synonyms": "окна пвх",
                    "excludes": "ремонт окон",
                    "cities": "",
                },
                headers=headers(org, user),
            )
        ).json()

        queries = [mask["query"] for mask in body["masks"]]

        assert queries[0].startswith("пластиковые окна -ремонт")
        # «-окон» в минусах не появляется: Вордстат минусует по всем формам
        # слова, и он вычеркнул бы «окна» из самой маски.
        assert "-окон" not in queries[0]
        assert "пластиковые окна тверь" in queries
        assert any("Тверь" in step for step in body["steps"])

    async def test_бриф_переживает_перезагрузку(
        self, client: AsyncClient, project: tuple[Organization, User, Project]
    ) -> None:
        org, user, row = project
        await client.put(
            f"/api/v1/projects/{row.id}/brief",
            json={"sells": "окна", "synonyms": "", "excludes": "", "cities": ""},
            headers=headers(org, user),
        )

        body = (
            await client.get(f"/api/v1/projects/{row.id}/brief", headers=headers(org, user))
        ).json()

        assert body["sells"] == "окна"

    async def test_повторное_сохранение_не_плодит_записи(
        self, client: AsyncClient, project: tuple[Organization, User, Project]
    ) -> None:
        org, user, row = project
        for sells in ("окна", "двери"):
            await client.put(
                f"/api/v1/projects/{row.id}/brief",
                json={"sells": sells, "synonyms": "", "excludes": "", "cities": ""},
                headers=headers(org, user),
            )

        body = (
            await client.get(f"/api/v1/projects/{row.id}/brief", headers=headers(org, user))
        ).json()

        assert body["sells"] == "двери"

    async def test_выгрузка_файлом_разбирается(
        self, client: AsyncClient, project: tuple[Organization, User, Project]
    ) -> None:
        org, user, row = project
        content = base64.b64encode("окна тверь;900\nкупить окна;500".encode()).decode()

        body = (
            await client.post(
                f"/api/v1/projects/{row.id}/keywords/import-file",
                json={"filename": "wordstat.csv", "content_base64": content},
                headers=headers(org, user),
            )
        ).json()

        assert body["added"] == 2

    async def test_нечитаемый_файл_объясняет_себя(
        self, client: AsyncClient, project: tuple[Organization, User, Project]
    ) -> None:
        """Ответ «не получилось» без причины заставляет гадать, а гадать здесь
        не о чем: файл либо не та кодировка, либо не таблица."""
        org, user, row = project
        content = base64.b64encode(b"PK\x03\x04\x00\x00\x00").decode()

        response = await client.post(
            f"/api/v1/projects/{row.id}/keywords/import-file",
            json={"filename": "битый.xlsx", "content_base64": content},
            headers=headers(org, user),
        )

        assert response.status_code == 422
        assert response.json()["error_code"] == "bad_file"


SITE = """
<html lang="ru"><head><title>Натяжные потолки в Твери</title></head><body>
  <h1>Натяжные потолки в Твери за 1 день</h1>
  <h2>Глянцевые полотна</h2><h2>Многоуровневые потолки</h2>
  <p>Монтаж от 350 ₽ за м². Багет в подарок.</p>
  <p>Адрес: г. Тверь, ул. Советская, д. 10</p>
</body></html>
"""


class TestОнбординг:
    """Что система прочитала с сайта и что осталось спросить руками."""

    async def _with_audit(
        self, session: AsyncSession, org: Organization, project_id: object
    ) -> None:
        from ads_os.services.profile import extract

        session.add(
            SiteAudit(
                organization_id=org.id,
                project_id=project_id,
                url="https://potolok.ru/",
                status=ModuleStatus.COMPLETED,
                client_profile=extract(SITE).as_dict(),
            )
        )
        await session.commit()

    async def test_без_проверки_сайта_говорится_прямо(
        self, client: AsyncClient, project: tuple[Organization, User, Project]
    ) -> None:
        """Пустая анкета без объяснения выглядит как поломка."""
        org, user, row = project

        body = (
            await client.get(f"/api/v1/projects/{row.id}/onboarding", headers=headers(org, user))
        ).json()

        assert body["has_audit"] is False
        assert body["filled"] == 0
        assert len(body["questions"]) > 0

    async def test_анкета_читается_с_сайта(
        self,
        session: AsyncSession,
        client: AsyncClient,
        project: tuple[Organization, User, Project],
    ) -> None:
        org, user, row = project
        await self._with_audit(session, org, row.id)

        body = (
            await client.get(f"/api/v1/projects/{row.id}/onboarding", headers=headers(org, user))
        ).json()

        assert body["profile"]["city"] == "Тверь"
        assert body["profile"]["niche_key"] == "stretch_ceilings"
        assert set(body["can_apply"]) == {"region", "niche", "brief"}

    async def test_принятое_переносится_в_проект(
        self,
        session: AsyncSession,
        client: AsyncClient,
        project: tuple[Organization, User, Project],
    ) -> None:
        org, user, row = project
        await self._with_audit(session, org, row.id)

        body = (
            await client.post(
                f"/api/v1/projects/{row.id}/onboarding/apply",
                json={"region": True, "niche": True, "brief": True},
                headers=headers(org, user),
            )
        ).json()

        await session.refresh(row)
        assert row.primary_region == "Тверь"
        assert row.niche == "stretch_ceilings"
        assert body["can_apply"] == []

        brief = (
            await client.get(f"/api/v1/projects/{row.id}/brief", headers=headers(org, user))
        ).json()
        assert "Глянцевые полотна" in brief["sells"]

    async def test_заполненное_человеком_не_переписывается(
        self,
        session: AsyncSession,
        client: AsyncClient,
        project: tuple[Organization, User, Project],
    ) -> None:
        """Разбор чужой страницы ошибается. Молча заменить решение человека —
        это месяц рекламы не в том регионе, который никто не заметит."""
        org, user, row = project
        row.primary_region = "Конаково"
        await session.commit()
        await self._with_audit(session, org, row.id)

        await client.post(
            f"/api/v1/projects/{row.id}/onboarding/apply",
            json={"region": True, "niche": False, "brief": False},
            headers=headers(org, user),
        )

        await session.refresh(row)
        assert row.primary_region == "Конаково"

    async def test_выборочный_перенос(
        self,
        session: AsyncSession,
        client: AsyncClient,
        project: tuple[Organization, User, Project],
    ) -> None:
        """Взять город, но не взять нишу — обычное дело."""
        org, user, row = project
        await self._with_audit(session, org, row.id)

        await client.post(
            f"/api/v1/projects/{row.id}/onboarding/apply",
            json={"region": True, "niche": False, "brief": False},
            headers=headers(org, user),
        )

        await session.refresh(row)
        assert row.primary_region == "Тверь"
        assert row.niche is None

    async def test_после_переноса_география_начинает_работать(
        self,
        session: AsyncSession,
        client: AsyncClient,
        project: tuple[Organization, User, Project],
    ) -> None:
        """Ради этого перенос и нужен: регион включает чистку по городам."""
        org, user, row = project
        await self._with_audit(session, org, row.id)
        await client.post(
            f"/api/v1/projects/{row.id}/onboarding/apply",
            json={"region": True, "niche": False, "brief": False},
            headers=headers(org, user),
        )

        body = (
            await client.post(
                f"/api/v1/projects/{row.id}/keywords/import",
                json={"text": "натяжные потолки москва\t900"},
                headers=headers(org, user),
            )
        ).json()

        assert body["irrelevant"] == 1
        assert body["cleaned"][0]["reason"] == "geo"


class TestРазметкаВВыгрузке:
    """Ссылки в файле размечены: он уходит прямо в Коммандер.

    Разметить его потом уже некому, а без меток отчёт показывает «переходы с
    рекламы» одной строкой — отключать нечего, не видно, что не работает.
    """

    async def _export(
        self,
        client: AsyncClient,
        session: AsyncSession,
        project: tuple[Organization, User, Project],
    ) -> str:
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
                selling_points=["Замер бесплатно"],
            )
        )
        await session.commit()
        await client.post(
            f"/api/v1/projects/{row.id}/keywords/import",
            json={"text": LIST},
            headers=headers(org, user),
        )

        response = await client.get(
            f"/api/v1/projects/{row.id}/campaign/export.csv", headers=headers(org, user)
        )
        return response.text

    async def test_метки_есть_в_ссылке(
        self,
        client: AsyncClient,
        session: AsyncSession,
        project: tuple[Organization, User, Project],
    ) -> None:
        body = await self._export(client, session, project)

        assert "utm_source=yandex" in body
        assert "utm_medium=cpc" in body

    async def test_подстановки_директа_не_закодированы(
        self,
        client: AsyncClient,
        session: AsyncSession,
        project: tuple[Organization, User, Project],
    ) -> None:
        """Закодированные скобки площадка не распознает, и в отчёт уедет
        буквальное «%7Bkeyword%7D» вместо фразы."""
        body = await self._export(client, session, project)

        assert "{keyword}" in body
        assert "%7B" not in body

    async def test_название_кампании_из_проекта(
        self,
        client: AsyncClient,
        session: AsyncSession,
        project: tuple[Organization, User, Project],
    ) -> None:
        """Проект называется «Окна Тверь» — в метке он должен быть узнаваем."""
        body = await self._export(client, session, project)

        assert "utm_campaign=okna_tver" in body


class TestОтветыНаВопросы:
    """Вопросы задаются — на них должно быть где ответить.

    Без этого экран показывает десять вопросов и не даёт записать ни одного
    ответа: человек уходит записывать их в блокнот, и в системе их больше нет.
    """

    async def test_ответ_сохраняется_и_возвращается(
        self, client: AsyncClient, project: tuple[Organization, User, Project]
    ) -> None:
        org, user, row = project

        body = (
            await client.put(
                f"/api/v1/projects/{row.id}/onboarding/answers",
                json={"answers": {"average_check": "35 000 ₽, маржа около 40%"}},
                headers=headers(org, user),
            )
        ).json()
        answered = next(q for q in body["questions"] if q["key"] == "average_check")

        assert answered["answer"] == "35 000 ₽, маржа около 40%"

    async def test_ответ_переживает_перезагрузку(
        self, client: AsyncClient, project: tuple[Organization, User, Project]
    ) -> None:
        org, user, row = project
        await client.put(
            f"/api/v1/projects/{row.id}/onboarding/answers",
            json={"answers": {"capacity": "20 заявок в неделю"}},
            headers=headers(org, user),
        )

        body = (
            await client.get(f"/api/v1/projects/{row.id}/onboarding", headers=headers(org, user))
        ).json()
        answered = next(q for q in body["questions"] if q["key"] == "capacity")

        assert answered["answer"] == "20 заявок в неделю"

    async def test_соседние_ответы_не_затираются(
        self, client: AsyncClient, project: tuple[Organization, User, Project]
    ) -> None:
        """Поля сохраняются по мере заполнения: присылать всю анкету каждый раз
        значило бы затирать ответ, который правят в соседней вкладке."""
        org, user, row = project
        for key, value in (("capacity", "20 в неделю"), ("where_leads_go", "amoCRM")):
            await client.put(
                f"/api/v1/projects/{row.id}/onboarding/answers",
                json={"answers": {key: value}},
                headers=headers(org, user),
            )

        body = (
            await client.get(f"/api/v1/projects/{row.id}/onboarding", headers=headers(org, user))
        ).json()
        saved = {q["key"]: q["answer"] for q in body["questions"]}

        assert saved["capacity"] == "20 в неделю"
        assert saved["where_leads_go"] == "amoCRM"

    async def test_пустой_ответ_стирает_прежний(
        self, client: AsyncClient, project: tuple[Organization, User, Project]
    ) -> None:
        """Человек, стерший строку, именно этого и хотел."""
        org, user, row = project
        await client.put(
            f"/api/v1/projects/{row.id}/onboarding/answers",
            json={"answers": {"capacity": "20"}},
            headers=headers(org, user),
        )

        body = (
            await client.put(
                f"/api/v1/projects/{row.id}/onboarding/answers",
                json={"answers": {"capacity": "   "}},
                headers=headers(org, user),
            )
        ).json()
        answered = next(q for q in body["questions"] if q["key"] == "capacity")

        assert answered["answer"] == ""

    async def test_чего_клиент_не_делает_попадает_в_бриф(
        self, client: AsyncClient, project: tuple[Organization, User, Project]
    ) -> None:
        """Спрашивать дважды об одном — значит выглядеть системой, которая не
        слушает: это ровно поле «чего не делаем» в брифе."""
        org, user, row = project

        await client.put(
            f"/api/v1/projects/{row.id}/onboarding/answers",
            json={"answers": {"not_selling": "ремонт окон, москитные сетки"}},
            headers=headers(org, user),
        )

        brief = (
            await client.get(f"/api/v1/projects/{row.id}/brief", headers=headers(org, user))
        ).json()

        assert brief["excludes"] == "ремонт окон, москитные сетки"

    async def test_заполненный_бриф_ответом_не_переписывается(
        self, client: AsyncClient, project: tuple[Organization, User, Project]
    ) -> None:
        org, user, row = project
        await client.put(
            f"/api/v1/projects/{row.id}/brief",
            json={"sells": "окна", "synonyms": "", "excludes": "своё", "cities": ""},
            headers=headers(org, user),
        )

        await client.put(
            f"/api/v1/projects/{row.id}/onboarding/answers",
            json={"answers": {"not_selling": "другое"}},
            headers=headers(org, user),
        )

        brief = (
            await client.get(f"/api/v1/projects/{row.id}/brief", headers=headers(org, user))
        ).json()

        assert brief["excludes"] == "своё"

    async def test_чужой_проект_недоступен(
        self,
        client: AsyncClient,
        session: AsyncSession,
        two_organizations: tuple[Organization, Organization],
        project: tuple[Organization, User, Project],
    ) -> None:
        org, user, _ = project
        _, stranger = two_organizations
        alien = Project(organization_id=stranger.id, name="Чужой")
        session.add(alien)
        await session.commit()

        response = await client.put(
            f"/api/v1/projects/{alien.id}/onboarding/answers",
            json={"answers": {"capacity": "10"}},
            headers=headers(org, user),
        )

        assert response.status_code == 404
