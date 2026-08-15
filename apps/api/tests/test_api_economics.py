"""Интеграционные тесты API экономики.

Проверяют связку целиком: маршрут, изоляция арендатора, расчёт, форма ответа.
Отдельно проверяется, что изоляция работает именно на уровне HTTP, а не только
в репозитории — SEC-001 сформулирован как требование к API.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from ads_os.api.deps import get_session
from ads_os.main import create_app
from ads_os.models import Organization, User

from .conftest import make_project, make_user


@pytest.fixture
async def client(session: AsyncSession) -> AsyncIterator[AsyncClient]:
    app = create_app()

    async def override_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = override_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def actors(
    session: AsyncSession, two_organizations: tuple[Organization, Organization]
) -> tuple[tuple[Organization, User], tuple[Organization, User]]:
    """По пользователю в каждой организации.

    Пользователь должен существовать: внешний ключ `created_by_id` не принимает
    произвольный идентификатор из заголовка, и это правильно — временный режим
    авторизации не должен позволять создавать записи от лица несуществующих
    людей.
    """
    org_a, org_b = two_organizations
    user_a = await make_user(session, org_a, "a@example.com")
    user_b = await make_user(session, org_b, "b@example.com")
    return (org_a, user_a), (org_b, user_b)


def headers(org: Organization, user: User, role: str = "specialist") -> dict[str, str]:
    return {
        "X-Organization-Id": str(org.id),
        "X-User-Id": str(user.id),
        "X-User-Role": role,
    }


class TestСлужебные:
    async def test_health_показывает_режим_работы(self, client: AsyncClient) -> None:
        """По ответу должно быть видно, что стенд работает на заглушках."""
        response = await client.get("/api/v1/health")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["ai_provider"] == "stub"
        assert body["ad_platform_adapter"] == "mock"

    async def test_идентификатор_запроса_возвращается(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/health")
        assert response.headers["X-Request-Id"]
        assert response.headers["X-Content-Type-Options"] == "nosniff"


class TestДоступ:
    async def test_без_входа_запрет(self, client: AsyncClient) -> None:
        """401, а не 403: интерфейс по этому коду отправляет на страницу входа.

        403 означал бы «вы вошли, но вам нельзя» — и человек остался бы на
        экране ошибки вместо формы входа.
        """
        response = await client.get("/api/v1/projects")
        assert response.status_code == 401
        assert response.json()["error_code"] == "not_authenticated"

    async def test_роль_viewer_не_создаёт_проекты(
        self,
        client: AsyncClient,
        actors: tuple[tuple[Organization, User], tuple[Organization, User]],
    ) -> None:
        (org_a, user_a), _ = actors
        response = await client.post(
            "/api/v1/projects",
            json={"name": "Проект"},
            headers=headers(org_a, user_a, role="viewer"),
        )
        assert response.status_code == 403


class TestSEC001НаУровнеAPI:
    async def test_чужой_проект_даёт_404(
        self,
        client: AsyncClient,
        session: AsyncSession,
        actors: tuple[tuple[Organization, User], tuple[Organization, User]],
    ) -> None:
        (org_a, user_a), (org_b, _) = actors
        foreign = await make_project(session, org_b, "Чужой проект")
        await session.commit()

        response = await client.get(
            f"/api/v1/projects/{foreign.id}", headers=headers(org_a, user_a)
        )

        assert response.status_code == 404
        assert response.json()["error_code"] == "not_found"

    async def test_экономика_чужого_проекта_недоступна(
        self,
        client: AsyncClient,
        session: AsyncSession,
        actors: tuple[tuple[Organization, User], tuple[Organization, User]],
    ) -> None:
        (org_a, user_a), (org_b, _) = actors
        foreign = await make_project(session, org_b, "Чужой проект")
        await session.commit()

        response = await client.put(
            f"/api/v1/projects/{foreign.id}/economics",
            json={"monthly_budget": "100000"},
            headers=headers(org_a, user_a),
        )

        assert response.status_code == 404


class TestЭкономика:
    async def test_у_нового_проекта_экономика_пуста_и_честна(
        self,
        client: AsyncClient,
        session: AsyncSession,
        actors: tuple[tuple[Organization, User], tuple[Organization, User]],
    ) -> None:
        (org_a, user_a), _ = actors
        project = await make_project(session, org_a, "Новый проект")
        await session.commit()

        response = await client.get(
            f"/api/v1/projects/{project.id}/economics", headers=headers(org_a, user_a)
        )

        assert response.status_code == 200
        body = response.json()
        assert body["input"] is None
        assert body["summary"]["mode"] == "insufficient"
        assert body["summary"]["can_optimize_by_sales"] is False
        assert body["summary"]["cta"]
        assert body["summary"]["break_even_cac"]["value"] is None
        assert body["summary"]["break_even_cac"]["availability"] == "unavailable"

    async def test_сохранение_и_расчёт(
        self,
        client: AsyncClient,
        session: AsyncSession,
        actors: tuple[tuple[Organization, User], tuple[Organization, User]],
    ) -> None:
        (org_a, user_a), _ = actors
        project = await make_project(session, org_a, "Проект")
        await session.commit()

        response = await client.put(
            f"/api/v1/projects/{project.id}/economics",
            json={
                "monthly_budget": "150000",
                "average_order_value": "6000",
                "main_conversion": "lead",
                "margin_percent": "45",
                "lead_to_sale_rate": "0.2",
            },
            headers=headers(org_a, user_a),
        )

        assert response.status_code == 200
        summary = response.json()["summary"]
        assert summary["mode"] == "complete"
        assert summary["can_optimize_by_sales"] is True
        assert summary["break_even_cac"]["value"] == "2700.00"
        assert summary["break_even_cpl"]["value"] == "540.00"
        # Целевой CAC выведен по нашему допущению — помечен ориентировочным.
        assert summary["target_cac"]["availability"] == "proxy"

    async def test_неполная_экономика_не_блокирует_проект(
        self,
        client: AsyncClient,
        session: AsyncSession,
        actors: tuple[tuple[Organization, User], tuple[Organization, User]],
    ) -> None:
        """Limited Economics Mode: работаем дальше, но без выводов о продажах."""
        (org_a, user_a), _ = actors
        project = await make_project(session, org_a, "Проект")
        await session.commit()

        response = await client.put(
            f"/api/v1/projects/{project.id}/economics",
            json={
                "monthly_budget": "150000",
                "average_order_value": "6000",
                "main_conversion": "lead",
            },
            headers=headers(org_a, user_a),
        )

        assert response.status_code == 200
        summary = response.json()["summary"]
        assert summary["mode"] == "limited"
        assert summary["can_optimize_by_sales"] is False
        assert "маржинальность" in summary["missing_recommended"]
        assert summary["cta"] == "Заполните экономику, чтобы включить оптимизацию по продажам"

    async def test_запись_поверх_чужого_изменения_отклоняется(
        self,
        client: AsyncClient,
        session: AsyncSession,
        actors: tuple[tuple[Organization, User], tuple[Organization, User]],
    ) -> None:
        """Экономика меняет пороги всех рекомендаций (v0.4 §100)."""
        (org_a, user_a), _ = actors
        project = await make_project(session, org_a, "Проект")
        await session.commit()

        first = await client.put(
            f"/api/v1/projects/{project.id}/economics",
            json={"monthly_budget": "150000"},
            headers=headers(org_a, user_a),
        )
        version = first.json()["input"]["version"]

        # Кто-то другой успел сохранить свою правку.
        await client.put(
            f"/api/v1/projects/{project.id}/economics",
            json={"monthly_budget": "200000"},
            headers=headers(org_a, user_a),
        )

        stale = await client.put(
            f"/api/v1/projects/{project.id}/economics",
            json={"monthly_budget": "180000", "expected_version": version},
            headers=headers(org_a, user_a),
        )

        assert stale.status_code == 409
        assert stale.json()["error_code"] == "version_conflict"

    async def test_отрицательный_бюджет_отклоняется(
        self,
        client: AsyncClient,
        session: AsyncSession,
        actors: tuple[tuple[Organization, User], tuple[Organization, User]],
    ) -> None:
        (org_a, user_a), _ = actors
        project = await make_project(session, org_a, "Проект")
        await session.commit()

        response = await client.put(
            f"/api/v1/projects/{project.id}/economics",
            json={"monthly_budget": "-5000"},
            headers=headers(org_a, user_a),
        )

        assert response.status_code == 422
        body = response.json()
        assert body["error_code"] == "validation_failed"
        # Наружу уходит путь до поля, но не содержимое ввода.
        assert body["details"]["fields"][0]["field"] == "monthly_budget"


class TestПроекты:
    async def test_создание_и_список(
        self,
        client: AsyncClient,
        actors: tuple[tuple[Organization, User], tuple[Organization, User]],
    ) -> None:
        (org_a, user_a), _ = actors

        created = await client.post(
            "/api/v1/projects",
            json={"name": "Apple Service Тверь", "primary_region": "Тверь"},
            headers=headers(org_a, user_a),
        )
        assert created.status_code == 201
        assert created.json()["status"] == "draft"

        mine = await client.get("/api/v1/projects", headers=headers(org_a, user_a))
        assert mine.json()["total"] == 1

        # У соседней организации список пуст.
        theirs = await client.get("/api/v1/projects", headers=headers(*actors[1]))
        assert theirs.json()["total"] == 0
