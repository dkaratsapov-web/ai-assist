"""Конкуренты проекта: добавление, разбор, сравнение."""

from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from ads_os.api.deps import get_session
from ads_os.api.v1.competitors import MAX_COMPETITORS
from ads_os.main import create_app
from ads_os.models import Competitor, Organization, Project, SiteAudit, User
from ads_os.models.audit import ModuleStatus

from .conftest import make_user

ALL_FEATURES = {
    "prices": True,
    "form": True,
    "phone": True,
    "messengers": True,
    "cta": True,
    "trust": True,
    "promo": True,
    "mobile": True,
    "analytics": True,
}

NO_FEATURES = dict.fromkeys(ALL_FEATURES, False)


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
    project = Project(
        organization_id=org.id,
        name="Apple Service Тверь",
        website_url="https://example.com/",
        created_by_id=user.id,
    )
    session.add(project)
    await session.commit()
    return org, user, project


def headers(org: Organization, user: User) -> dict[str, str]:
    return {
        "X-Organization-Id": str(org.id),
        "X-User-Id": str(user.id),
        "X-User-Role": "specialist",
    }


async def add_rival(
    session: AsyncSession,
    project_ctx: tuple[Organization, User, Project],
    url: str,
    features: dict[str, bool] | None = None,
) -> Competitor:
    org, _, project = project_ctx
    competitor = Competitor(
        organization_id=org.id,
        project_id=project.id,
        url=url,
        title=url,
        status=ModuleStatus.COMPLETED if features else ModuleStatus.QUEUED,
        features=features or {},
    )
    session.add(competitor)
    await session.commit()
    return competitor


async def add_audit(
    session: AsyncSession,
    project_ctx: tuple[Organization, User, Project],
    features: dict[str, bool],
) -> SiteAudit:
    org, _, project = project_ctx
    audit = SiteAudit(
        organization_id=org.id,
        project_id=project.id,
        url="https://example.com/",
        status=ModuleStatus.COMPLETED,
        score=70,
        categories=[],
        issues=[],
        features=features,
    )
    session.add(audit)
    await session.commit()
    return audit


class TestДобавление:
    async def test_конкурент_ставится_в_очередь(
        self, client: AsyncClient, project_ctx: tuple[Organization, User, Project]
    ) -> None:
        org, user, project = project_ctx

        with patch("ads_os.api.v1.competitors.enqueue_competitor") as enqueue:
            response = await client.post(
                f"/api/v1/projects/{project.id}/competitors",
                headers=headers(org, user),
                json={"url": "https://rival.ru/", "title": "Главный конкурент"},
            )

        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "queued"
        assert body["title"] == "Главный конкурент"
        assert enqueue.call_count == 1

    async def test_дубль_адреса_отклоняется(
        self,
        client: AsyncClient,
        session: AsyncSession,
        project_ctx: tuple[Organization, User, Project],
    ) -> None:
        """Дубль считался бы за двоих и искажал сравнение."""
        org, user, project = project_ctx
        await add_rival(session, project_ctx, "https://rival.ru/", ALL_FEATURES)

        with patch("ads_os.api.v1.competitors.enqueue_competitor"):
            response = await client.post(
                f"/api/v1/projects/{project.id}/competitors",
                headers=headers(org, user),
                json={"url": "https://rival.ru/"},
            )

        assert response.status_code == 409

    async def test_количество_ограничено(
        self,
        client: AsyncClient,
        session: AsyncSession,
        project_ctx: tuple[Organization, User, Project],
    ) -> None:
        org, user, project = project_ctx
        for i in range(MAX_COMPETITORS):
            await add_rival(session, project_ctx, f"https://rival-{i}.ru/", ALL_FEATURES)

        with patch("ads_os.api.v1.competitors.enqueue_competitor"):
            response = await client.post(
                f"/api/v1/projects/{project.id}/competitors",
                headers=headers(org, user),
                json={"url": "https://one-more.ru/"},
            )

        assert response.status_code == 422
        assert response.json()["error_code"] == "too_many_competitors"

    async def test_недоступная_очередь_не_теряет_введённый_адрес(
        self, client: AsyncClient, project_ctx: tuple[Organization, User, Project]
    ) -> None:
        """Конкурент остаётся добавленным, проверку можно запустить кнопкой."""
        org, user, project = project_ctx

        with patch(
            "ads_os.api.v1.competitors.enqueue_competitor",
            side_effect=OSError("Connection refused"),
        ):
            response = await client.post(
                f"/api/v1/projects/{project.id}/competitors",
                headers=headers(org, user),
                json={"url": "https://rival.ru/"},
            )

        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "not_started"
        assert body["error_reason"]

    async def test_чужой_проект_недоступен(
        self,
        client: AsyncClient,
        session: AsyncSession,
        project_ctx: tuple[Organization, User, Project],
        two_organizations: tuple[Organization, Organization],
    ) -> None:
        _, other_org = two_organizations
        other_user = await make_user(session, other_org, "other@example.com")
        await session.commit()
        _, _, project = project_ctx

        response = await client.post(
            f"/api/v1/projects/{project.id}/competitors",
            headers=headers(other_org, other_user),
            json={"url": "https://rival.ru/"},
        )

        assert response.status_code == 404


class TestУдаление:
    async def test_конкурент_удаляется(
        self,
        client: AsyncClient,
        session: AsyncSession,
        project_ctx: tuple[Organization, User, Project],
    ) -> None:
        org, user, project = project_ctx
        rival = await add_rival(session, project_ctx, "https://rival.ru/", ALL_FEATURES)

        response = await client.delete(
            f"/api/v1/projects/{project.id}/competitors/{rival.id}",
            headers=headers(org, user),
        )

        assert response.status_code == 204
        listing = await client.get(
            f"/api/v1/projects/{project.id}/competitors", headers=headers(org, user)
        )
        assert listing.json()["total"] == 0

    async def test_чужой_конкурент_не_удаляется(
        self,
        client: AsyncClient,
        session: AsyncSession,
        project_ctx: tuple[Organization, User, Project],
        two_organizations: tuple[Organization, Organization],
    ) -> None:
        _, _, project = project_ctx
        _, other_org = two_organizations
        other_user = await make_user(session, other_org, "other@example.com")
        rival = await add_rival(session, project_ctx, "https://rival.ru/", ALL_FEATURES)
        await session.commit()

        response = await client.delete(
            f"/api/v1/projects/{project.id}/competitors/{rival.id}",
            headers=headers(other_org, other_user),
        )

        assert response.status_code == 404


class TestСравнение:
    async def test_без_конкурентов_вывода_нет(
        self, client: AsyncClient, project_ctx: tuple[Organization, User, Project]
    ) -> None:
        org, user, project = project_ctx

        response = await client.get(
            f"/api/v1/projects/{project.id}/comparison", headers=headers(org, user)
        )

        body = response.json()
        assert response.status_code == 200
        assert body["rivals_checked"] == 0
        assert body["summary"] is None
        assert body["own_site_checked"] is False

    async def test_непроверенный_конкурент_в_сравнение_не_идёт(
        self,
        client: AsyncClient,
        session: AsyncSession,
        project_ctx: tuple[Organization, User, Project],
    ) -> None:
        """Иначе он выглядел бы как конкурент, у которого нет ничего."""
        org, user, project = project_ctx
        await add_rival(session, project_ctx, "https://rival.ru/")

        response = await client.get(
            f"/api/v1/projects/{project.id}/comparison", headers=headers(org, user)
        )

        assert response.json()["rivals_checked"] == 0

    async def test_пробел_виден_в_строке(
        self,
        client: AsyncClient,
        session: AsyncSession,
        project_ctx: tuple[Organization, User, Project],
    ) -> None:
        org, user, project = project_ctx
        await add_audit(session, project_ctx, NO_FEATURES)
        await add_rival(session, project_ctx, "https://a.ru/", ALL_FEATURES)
        await add_rival(session, project_ctx, "https://b.ru/", ALL_FEATURES)

        response = await client.get(
            f"/api/v1/projects/{project.id}/comparison", headers=headers(org, user)
        )

        body = response.json()
        assert body["own_site_checked"] is True
        assert body["rivals_checked"] == 2
        gaps = [row for row in body["rows"] if row["is_gap"]]
        assert len(gaps) == len(ALL_FEATURES)
        assert body["summary"] is not None

    async def test_аудит_без_признаков_не_считается_проверкой(
        self,
        client: AsyncClient,
        session: AsyncSession,
        project_ctx: tuple[Organization, User, Project],
    ) -> None:
        """Старый аудит снят до появления сравнения — признаков в нём нет."""
        org, user, project = project_ctx
        await add_audit(session, project_ctx, {})
        await add_rival(session, project_ctx, "https://a.ru/", ALL_FEATURES)

        response = await client.get(
            f"/api/v1/projects/{project.id}/comparison", headers=headers(org, user)
        )

        assert response.json()["own_site_checked"] is False

    async def test_каждая_строка_объясняет_зачем_признак(
        self, client: AsyncClient, project_ctx: tuple[Organization, User, Project]
    ) -> None:
        org, user, project = project_ctx

        response = await client.get(
            f"/api/v1/projects/{project.id}/comparison", headers=headers(org, user)
        )

        assert all(row["why"] for row in response.json()["rows"])

    async def test_конкуренты_соседнего_проекта_не_попадают(
        self,
        client: AsyncClient,
        session: AsyncSession,
        project_ctx: tuple[Organization, User, Project],
    ) -> None:
        org, user, project = project_ctx
        neighbour = Project(organization_id=org.id, name="Соседний")
        session.add(neighbour)
        await session.flush()
        session.add(
            Competitor(
                organization_id=org.id,
                project_id=neighbour.id,
                url="https://neighbour-rival.ru/",
                status=ModuleStatus.COMPLETED,
                features=ALL_FEATURES,
            )
        )
        await session.commit()

        response = await client.get(
            f"/api/v1/projects/{project.id}/comparison", headers=headers(org, user)
        )

        assert response.json()["rivals_checked"] == 0


MY_PAGE = """
<html><body><h1>Натяжные потолки</h1>
<p>Монтаж от 450 ₽ за м². Гарантия 12 месяцев.</p>
<form><input name="a"><input name="b"><input name="c"><input name="d"></form>
</body></html>
"""

RIVAL_PAGE = """
<html><body><h1>Натяжные потолки за 1 день</h1>
<p>Цена от 290 ₽ за м². Замер бесплатно. Скидка 20%.</p>
<form><input name="phone"></form>
</body></html>
"""


class TestПредметноеСравнение:
    """Не «есть цены — нет цен», а насколько именно ваша цена выше.

    Ради этого сравнение и существует: по галочке «цены есть у обоих» решение о
    том, чем отличаться от конкурента, принять невозможно.
    """

    async def _setup(
        self, session: AsyncSession, project_ctx: tuple[Organization, User, Project]
    ) -> None:
        from ads_os.services.offer import extract

        org, _, project = project_ctx
        session.add(
            SiteAudit(
                organization_id=org.id,
                project_id=project.id,
                url="https://example.com/",
                status=ModuleStatus.COMPLETED,
                score=70,
                categories=[],
                issues=[],
                features=ALL_FEATURES,
                offer=extract(MY_PAGE).as_dict(),
            )
        )
        session.add(
            Competitor(
                organization_id=org.id,
                project_id=project.id,
                url="https://rival.ru/",
                title="Конкурент",
                status=ModuleStatus.COMPLETED,
                features=ALL_FEATURES,
                offer=extract(RIVAL_PAGE).as_dict(),
            )
        )
        await session.commit()

    async def test_цены_сравниваются_числами(
        self,
        client: AsyncClient,
        session: AsyncSession,
        project_ctx: tuple[Organization, User, Project],
    ) -> None:
        org, user, project = project_ctx
        await self._setup(session, project_ctx)

        body = (
            await client.get(
                f"/api/v1/projects/{project.id}/comparison", headers=headers(org, user)
            )
        ).json()
        row = next(r for r in body["offer_rows"] if r["key"] == "price")

        assert body["offer_has_data"] is True
        assert "450" in row["verdict"] and "290" in row["verdict"]
        assert row["is_gap"] is True

    async def test_цитата_конкурента_подписана_адресом(
        self,
        client: AsyncClient,
        session: AsyncSession,
        project_ctx: tuple[Organization, User, Project],
    ) -> None:
        """Без адреса цитату не проверить, а вся её ценность в проверяемости."""
        org, user, project = project_ctx
        await self._setup(session, project_ctx)

        body = (
            await client.get(
                f"/api/v1/projects/{project.id}/comparison", headers=headers(org, user)
            )
        ).json()
        row = next(r for r in body["offer_rows"] if r["key"] == "deadline")

        assert row["rivals"][0]["url"] == "https://rival.ru/"
        assert "1 день" in row["rivals"][0]["value"]

    async def test_старые_разборы_без_условий_не_ломают_ответ(
        self,
        client: AsyncClient,
        session: AsyncSession,
        project_ctx: tuple[Organization, User, Project],
    ) -> None:
        """Конкуренты, разобранные до появления условий, лежат с пустым полем."""
        org, user, project = project_ctx
        await add_audit(session, project_ctx, ALL_FEATURES)
        await add_rival(session, project_ctx, "https://old.ru/", ALL_FEATURES)

        response = await client.get(
            f"/api/v1/projects/{project.id}/comparison", headers=headers(org, user)
        )

        assert response.status_code == 200
        assert response.json()["offer_has_data"] is False
