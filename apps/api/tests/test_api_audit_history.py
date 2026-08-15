"""История проверок сайта (v0.3 §62).

Главное, ради чего история существует: показать, помогли доработки сайта или
нет. Поэтому проверяется в первую очередь расчёт изменения балла, а не сам факт
списка.
"""

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
    project = Project(
        organization_id=org.id,
        name="Проект",
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


async def add_audit(
    session: AsyncSession,
    ctx: tuple[Organization, User, Project],
    *,
    score: int | None = None,
    status: ModuleStatus = ModuleStatus.COMPLETED,
    issues: list[dict[str, str]] | None = None,
    error_reason: str | None = None,
) -> SiteAudit:
    """Добавляет проверку. Порядок вызовов задаёт порядок во времени."""
    org, _, project = ctx
    audit = SiteAudit(
        organization_id=org.id,
        project_id=project.id,
        url="https://example.com/",
        status=status,
        score=score,
        categories=[],
        issues=issues or [],
        error_reason=error_reason,
        features={},
    )
    session.add(audit)
    # Отдельный flush на каждую запись: created_at проставляет база, и без него
    # все записи получили бы одинаковое время, а порядок истории стал бы
    # случайным.
    await session.flush()
    await session.commit()
    return audit


class TestПустаяИстория:
    async def test_без_проверок_список_пуст(
        self, client: AsyncClient, project_ctx: tuple[Organization, User, Project]
    ) -> None:
        org, user, project = project_ctx

        response = await client.get(
            f"/api/v1/projects/{project.id}/audits", headers=headers(org, user)
        )

        assert response.status_code == 200
        assert response.json() == {"items": [], "total": 0}


class TestПорядок:
    async def test_новые_проверки_сверху(
        self,
        client: AsyncClient,
        session: AsyncSession,
        project_ctx: tuple[Organization, User, Project],
    ) -> None:
        org, user, project = project_ctx
        await add_audit(session, project_ctx, score=40)
        await add_audit(session, project_ctx, score=80)

        response = await client.get(
            f"/api/v1/projects/{project.id}/audits", headers=headers(org, user)
        )

        scores = [item["score"] for item in response.json()["items"]]
        assert scores == [80, 40]


class TestИзменениеБалла:
    async def test_первая_проверка_без_сравнения(
        self,
        client: AsyncClient,
        session: AsyncSession,
        project_ctx: tuple[Organization, User, Project],
    ) -> None:
        """Сравнивать не с чем — значит и показывать нечего."""
        org, user, project = project_ctx
        await add_audit(session, project_ctx, score=55)

        response = await client.get(
            f"/api/v1/projects/{project.id}/audits", headers=headers(org, user)
        )

        assert response.json()["items"][0]["score_delta"] is None

    async def test_рост_балла(
        self,
        client: AsyncClient,
        session: AsyncSession,
        project_ctx: tuple[Organization, User, Project],
    ) -> None:
        org, user, project = project_ctx
        await add_audit(session, project_ctx, score=55)
        await add_audit(session, project_ctx, score=78)

        items = (
            await client.get(
                f"/api/v1/projects/{project.id}/audits", headers=headers(org, user)
            )
        ).json()["items"]

        assert items[0]["score_delta"] == 23
        assert items[1]["score_delta"] is None

    async def test_падение_балла(
        self,
        client: AsyncClient,
        session: AsyncSession,
        project_ctx: tuple[Organization, User, Project],
    ) -> None:
        org, user, project = project_ctx
        await add_audit(session, project_ctx, score=78)
        await add_audit(session, project_ctx, score=60)

        items = (
            await client.get(
                f"/api/v1/projects/{project.id}/audits", headers=headers(org, user)
            )
        ).json()["items"]

        assert items[0]["score_delta"] == -18

    async def test_неудачный_запуск_не_ломает_сравнение(
        self,
        client: AsyncClient,
        session: AsyncSession,
        project_ctx: tuple[Organization, User, Project],
    ) -> None:
        """Сайт, который не открылся, — не повод показать падение на 70 пунктов."""
        org, user, project = project_ctx
        await add_audit(session, project_ctx, score=70)
        await add_audit(
            session,
            project_ctx,
            status=ModuleStatus.FAILED,
            error_reason="сервер не ответил вовремя",
        )
        await add_audit(session, project_ctx, score=75)

        items = (
            await client.get(
                f"/api/v1/projects/{project.id}/audits", headers=headers(org, user)
            )
        ).json()["items"]

        # Свежая проверка сравнивается с последней удачной, а не с упавшей.
        assert items[0]["score_delta"] == 5
        # У самой упавшей изменения нет вовсе.
        assert items[1]["score_delta"] is None
        assert items[1]["error_reason"] == "сервер не ответил вовремя"


class TestСодержимое:
    async def test_критические_находки_видны_в_истории(
        self,
        client: AsyncClient,
        session: AsyncSession,
        project_ctx: tuple[Organization, User, Project],
    ) -> None:
        """По истории должно быть видно, когда запуск был закрыт."""
        org, user, project = project_ctx
        await add_audit(
            session,
            project_ctx,
            score=35,
            issues=[
                {
                    "category": "tracking",
                    "severity": "critical",
                    "title": "Нет Метрики",
                    "action": "Установите счётчик",
                }
            ],
        )

        item = (
            await client.get(
                f"/api/v1/projects/{project.id}/audits", headers=headers(org, user)
            )
        ).json()["items"][0]

        assert item["can_launch"] is False

    async def test_списка_находок_в_истории_нет(
        self,
        client: AsyncClient,
        session: AsyncSession,
        project_ctx: tuple[Organization, User, Project],
    ) -> None:
        """История отвечает «лучше или хуже», подробности — в последнем результате."""
        org, user, project = project_ctx
        await add_audit(session, project_ctx, score=50)

        item = (
            await client.get(
                f"/api/v1/projects/{project.id}/audits", headers=headers(org, user)
            )
        ).json()["items"][0]

        assert "issues" not in item
        assert "categories" not in item


class TestИзоляция:
    async def test_чужая_история_недоступна(
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

        response = await client.get(
            f"/api/v1/projects/{project.id}/audits", headers=headers(other_org, other_user)
        )

        assert response.status_code == 404

    async def test_история_соседнего_проекта_не_подмешивается(
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
            SiteAudit(
                organization_id=org.id,
                project_id=neighbour.id,
                url="https://neighbour.example/",
                status=ModuleStatus.COMPLETED,
                score=99,
                categories=[],
                issues=[],
                features={},
            )
        )
        await session.commit()

        response = await client.get(
            f"/api/v1/projects/{project.id}/audits", headers=headers(org, user)
        )

        assert response.json()["total"] == 0
