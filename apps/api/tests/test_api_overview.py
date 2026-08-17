"""Сводка по проектам — главный экран."""

from __future__ import annotations

from collections.abc import AsyncIterator
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from ads_os.api.deps import get_session
from ads_os.main import create_app
from ads_os.models import (
    Competitor,
    Organization,
    Project,
    ProjectEconomics,
    SiteAudit,
    User,
)
from ads_os.models.audit import ModuleStatus
from ads_os.models.project import MainConversion

from .conftest import make_user

CRITICAL_ISSUE = {
    "category": "tracking",
    "severity": "critical",
    "title": "Не установлена Яндекс Метрика",
    "action": "Установите счётчик",
}


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


async def make_project(
    session: AsyncSession, org: Organization, name: str, website: str | None = None
) -> Project:
    project = Project(organization_id=org.id, name=name, website_url=website)
    session.add(project)
    await session.flush()
    return project


class TestПустаяСводка:
    async def test_без_проектов_сводка_пуста(
        self, client: AsyncClient, org_ctx: tuple[Organization, User]
    ) -> None:
        org, user = org_ctx

        response = await client.get("/api/v1/overview", headers=headers(org, user))

        body = response.json()
        assert response.status_code == 200
        assert body["total"] == 0
        assert body["projects"] == []
        assert body["needs_attention"] == 0


class TestСодержимое:
    async def test_проект_описан_состоянием_а_не_цифрами(
        self,
        client: AsyncClient,
        session: AsyncSession,
        org_ctx: tuple[Organization, User],
    ) -> None:
        """Расходов и лидов в сводке нет: рекламный кабинет не подключён."""
        org, user = org_ctx
        await make_project(session, org, "Без сайта")
        await session.commit()

        response = await client.get("/api/v1/overview", headers=headers(org, user))

        body = response.json()
        assert body["ad_platform_connected"] is False
        row = body["projects"][0]
        assert row["current_step"] == "onboarding"
        assert row["current_step_label"] == "Онбординг"
        assert row["total_count"] == 10
        assert row["next_action"]
        assert "spend" not in row and "leads" not in row

    async def test_состояние_собирается_из_всех_модулей(
        self,
        client: AsyncClient,
        session: AsyncSession,
        org_ctx: tuple[Organization, User],
    ) -> None:
        org, user = org_ctx
        project = await make_project(session, org, "Полный", "https://example.com/")
        session.add(
            SiteAudit(
                organization_id=org.id,
                project_id=project.id,
                url="https://example.com/",
                status=ModuleStatus.COMPLETED,
                score=78,
                categories=[],
                issues=[],
                features={"form": True},
            )
        )
        session.add(
            Competitor(
                organization_id=org.id,
                project_id=project.id,
                url="https://rival.ru/",
                status=ModuleStatus.COMPLETED,
                features={"form": True},
            )
        )
        session.add(
            ProjectEconomics(
                organization_id=org.id,
                project_id=project.id,
                monthly_budget=Decimal("100000"),
                average_order_value=Decimal("5000"),
                main_conversion=MainConversion.LEAD,
                margin_percent=Decimal("40"),
                lead_to_sale_rate=Decimal("0.3"),
                version=1,
            )
        )
        await session.commit()

        response = await client.get("/api/v1/overview", headers=headers(org, user))

        row = response.json()["projects"][0]
        assert row["audit_status"] == "completed"
        assert row["audit_score"] == 78
        assert row["competitors_checked"] == 1
        assert row["economics_mode"] == "complete"
        assert row["can_launch"] is True

    async def test_критические_находки_снимают_право_на_запуск(
        self,
        client: AsyncClient,
        session: AsyncSession,
        org_ctx: tuple[Organization, User],
    ) -> None:
        org, user = org_ctx
        project = await make_project(session, org, "С проблемой", "https://example.com/")
        session.add(
            SiteAudit(
                organization_id=org.id,
                project_id=project.id,
                url="https://example.com/",
                status=ModuleStatus.COMPLETED,
                score=35,
                categories=[],
                issues=[CRITICAL_ISSUE],
                features={},
            )
        )
        await session.commit()

        response = await client.get("/api/v1/overview", headers=headers(org, user))

        assert response.json()["projects"][0]["can_launch"] is False

    async def test_берётся_последний_аудит_а_не_первый(
        self,
        client: AsyncClient,
        session: AsyncSession,
        org_ctx: tuple[Organization, User],
    ) -> None:
        """История аудитов хранится целиком, показывать нужно свежий."""
        org, user = org_ctx
        project = await make_project(session, org, "С историей", "https://example.com/")
        for score in (10, 90):
            session.add(
                SiteAudit(
                    organization_id=org.id,
                    project_id=project.id,
                    url="https://example.com/",
                    status=ModuleStatus.COMPLETED,
                    score=score,
                    categories=[],
                    issues=[],
                    features={},
                )
            )
            await session.flush()
        await session.commit()

        response = await client.get("/api/v1/overview", headers=headers(org, user))

        assert response.json()["projects"][0]["audit_score"] == 90


class TestТребуютВнимания:
    async def test_считаются_только_те_где_ход_за_человеком(
        self,
        client: AsyncClient,
        session: AsyncSession,
        org_ctx: tuple[Organization, User],
    ) -> None:
        """Иначе внимания требовали бы все проекты сразу и счётчик обесценился."""
        org, user = org_ctx
        await make_project(session, org, "Требует действия")

        done = await make_project(session, org, "Всё сделано", "https://example.com/")
        done.niche = "plastic_windows"
        session.add(
            SiteAudit(
                organization_id=org.id,
                project_id=done.id,
                url="https://example.com/",
                status=ModuleStatus.COMPLETED,
                score=90,
                categories=[],
                issues=[],
                features={},
            )
        )
        session.add(
            Competitor(
                organization_id=org.id,
                project_id=done.id,
                url="https://rival.ru/",
                status=ModuleStatus.COMPLETED,
                features={"form": True},
            )
        )
        session.add(
            ProjectEconomics(
                organization_id=org.id,
                project_id=done.id,
                monthly_budget=Decimal("100000"),
                average_order_value=Decimal("5000"),
                main_conversion=MainConversion.LEAD,
                margin_percent=Decimal("40"),
                lead_to_sale_rate=Decimal("0.3"),
                version=1,
            )
        )
        await session.commit()

        response = await client.get("/api/v1/overview", headers=headers(org, user))

        assert response.json()["needs_attention"] == 1


class TestИзоляция:
    async def test_чужие_проекты_не_видны(
        self,
        client: AsyncClient,
        session: AsyncSession,
        two_organizations: tuple[Organization, Organization],
        org_ctx: tuple[Organization, User],
    ) -> None:
        org, user = org_ctx
        _, other_org = two_organizations
        await make_project(session, org, "Мой")
        await make_project(session, other_org, "Чужой")
        await session.commit()

        response = await client.get("/api/v1/overview", headers=headers(org, user))

        names = [p["name"] for p in response.json()["projects"]]
        assert names == ["Мой"]

    async def test_чужой_аудит_не_подмешивается(
        self,
        client: AsyncClient,
        session: AsyncSession,
        two_organizations: tuple[Organization, Organization],
        org_ctx: tuple[Organization, User],
    ) -> None:
        """Соединение по проектам без фильтра по организации давало бы утечку."""
        org, user = org_ctx
        _, other_org = two_organizations
        mine = await make_project(session, org, "Мой", "https://example.com/")
        session.add(
            SiteAudit(
                organization_id=other_org.id,
                project_id=mine.id,
                url="https://example.com/",
                status=ModuleStatus.COMPLETED,
                score=99,
                categories=[],
                issues=[],
                features={},
            )
        )
        await session.commit()

        response = await client.get("/api/v1/overview", headers=headers(org, user))

        assert response.json()["projects"][0]["audit_score"] is None
