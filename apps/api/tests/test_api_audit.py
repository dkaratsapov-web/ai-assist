"""Аудит сайта: запуск, обработка, результат."""

from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ads_os.api.deps import get_session
from ads_os.main import create_app
from ads_os.models import Organization, Project, SiteAudit, User
from ads_os.models.audit import ModuleStatus
from ads_os.services.crawler.fetcher import FetchedPage, FetchError

from .conftest import make_user

GOOD_PAGE = """
<html><head><title>Ремонт Apple</title>
<meta name="viewport" content="width=device-width"><script>ym(99887766,'init',{});</script>
</head><body><h1>Ремонт iPhone за 1 час</h1><p>от 3 500 ₽. Гарантия 12 месяцев, отзывы.</p>
<form><input name="phone"><button>Оставить заявку</button></form>
<p>+7 (900) 123-45-67</p></body></html>
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
async def project_with_site(
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
    await session.flush()
    await session.commit()
    return org, user, project


async def _make_audit(
    session: AsyncSession,
    project_with_site: tuple[Organization, User, Project],
    status: ModuleStatus,
    **fields: object,
) -> SiteAudit:
    org, _, project = project_with_site
    audit = SiteAudit(
        organization_id=org.id,
        project_id=project.id,
        url="https://example.com/",
        status=status,
        categories=[],
        issues=[],
        **fields,
    )
    session.add(audit)
    await session.commit()
    return audit


def headers(org: Organization, user: User) -> dict[str, str]:
    return {
        "X-Organization-Id": str(org.id),
        "X-User-Id": str(user.id),
        "X-User-Role": "specialist",
    }


class TestЗапуск:
    async def test_аудит_ставится_в_очередь(
        self, client: AsyncClient, project_with_site: tuple[Organization, User, Project]
    ) -> None:
        org, user, project = project_with_site

        with patch("ads_os.api.v1.audit.enqueue_site_audit") as enqueue:
            response = await client.post(
                f"/api/v1/projects/{project.id}/audit", headers=headers(org, user)
            )

        assert response.status_code == 202
        body = response.json()
        assert body["status"] == "queued"
        assert body["score"] is None
        # Задача поставлена ровно одна, и адрес передан аргументом: воркер
        # краулера не имеет доступа к базе и не может прочитать его сам.
        assert enqueue.call_count == 1
        assert enqueue.call_args.args[1] == "https://example.com/"

    async def test_недоступная_очередь_не_оставляет_зависший_аудит(
        self, client: AsyncClient, project_with_site: tuple[Organization, User, Project]
    ) -> None:
        """Redis лежит — это состояние инфраструктуры, а не дефект кода.

        Важнее ответа то, что запись не остаётся: аудит со статусом «в очереди»,
        которого нет в очереди, навсегда заблокировал бы повторный запуск.
        """
        org, user, project = project_with_site

        with patch(
            "ads_os.api.v1.audit.enqueue_site_audit",
            side_effect=OSError("Connection refused"),
        ):
            first = await client.post(
                f"/api/v1/projects/{project.id}/audit", headers=headers(org, user)
            )

        assert first.status_code == 503
        assert first.json()["error_code"] == "queue_unavailable"
        assert first.json()["retryable"] is True

        # Повторная попытка после починки очереди проходит, а не упирается в 409.
        with patch("ads_os.api.v1.audit.enqueue_site_audit"):
            second = await client.post(
                f"/api/v1/projects/{project.id}/audit", headers=headers(org, user)
            )

        assert second.status_code == 202

    async def test_без_адреса_сайта_запуск_невозможен(
        self,
        client: AsyncClient,
        session: AsyncSession,
        two_organizations: tuple[Organization, Organization],
    ) -> None:
        org, _ = two_organizations
        user = await make_user(session, org, "u@example.com")
        project = Project(organization_id=org.id, name="Без сайта", created_by_id=user.id)
        session.add(project)
        await session.commit()

        response = await client.post(
            f"/api/v1/projects/{project.id}/audit", headers=headers(org, user)
        )

        assert response.status_code == 422
        assert response.json()["error_code"] == "website_missing"

    async def test_повторный_запуск_отклоняется(
        self, client: AsyncClient, project_with_site: tuple[Organization, User, Project]
    ) -> None:
        """Краулер ходит по чужому сайту — дублировать работу незачем."""
        org, user, project = project_with_site

        with patch("ads_os.api.v1.audit.enqueue_site_audit"):
            first = await client.post(
                f"/api/v1/projects/{project.id}/audit", headers=headers(org, user)
            )
            second = await client.post(
                f"/api/v1/projects/{project.id}/audit", headers=headers(org, user)
            )

        assert first.status_code == 202
        assert second.status_code == 409
        assert second.json()["error_code"] == "audit_already_running"

    async def test_чужой_проект_недоступен(
        self,
        client: AsyncClient,
        session: AsyncSession,
        project_with_site: tuple[Organization, User, Project],
        two_organizations: tuple[Organization, Organization],
    ) -> None:
        _, other_org = two_organizations
        other_user = await make_user(session, other_org, "other@example.com")
        await session.commit()
        _, _, project = project_with_site

        response = await client.post(
            f"/api/v1/projects/{project.id}/audit", headers=headers(other_org, other_user)
        )

        assert response.status_code == 404


class TestРезультат:
    async def test_до_первого_запуска_результата_нет(
        self, client: AsyncClient, project_with_site: tuple[Organization, User, Project]
    ) -> None:
        org, user, project = project_with_site

        response = await client.get(
            f"/api/v1/projects/{project.id}/audit", headers=headers(org, user)
        )

        assert response.status_code == 200
        assert response.json() is None

    async def test_возвращается_последний_аудит(
        self, client: AsyncClient, project_with_site: tuple[Organization, User, Project]
    ) -> None:
        org, user, project = project_with_site

        with patch("ads_os.api.v1.audit.enqueue_site_audit"):
            await client.post(f"/api/v1/projects/{project.id}/audit", headers=headers(org, user))

        response = await client.get(
            f"/api/v1/projects/{project.id}/audit", headers=headers(org, user)
        )

        body = response.json()
        assert body["status"] == "queued"
        assert body["url"] == "https://example.com/"


OK_FETCH = {
    "ok": True,
    "final_url": "https://example.com/",
    "status_code": 200,
    "html": GOOD_PAGE,
}


class TestЗагрузка:
    """Первая задача цепочки. Выполняется в воркере краулера — без базы.

    Тесты синхронные намеренно: задача сама поднимает цикл событий через
    asyncio.run, а вложить его в уже работающий цикл нельзя.
    """

    def test_страница_отдаётся_дальше_как_данные(self) -> None:
        from ads_os.worker.tasks.audit import fetch_site_page

        page = FetchedPage(
            url="https://example.com/",
            final_url="https://example.com/final",
            status_code=200,
            content_type="text/html",
            html=GOOD_PAGE,
        )

        async def fake_fetch(url: str, **kwargs: object) -> FetchedPage:
            return page

        with patch("ads_os.worker.tasks.audit.fetch_page", fake_fetch):
            result = fetch_site_page("https://example.com/")

        assert result["ok"] is True
        assert result["final_url"] == "https://example.com/final"
        assert result["html"] == GOOD_PAGE

    def test_ошибка_загрузки_не_роняет_цепочку(self) -> None:
        """Причина передаётся дальше значением: разбирать её будет второй воркер."""
        from ads_os.worker.tasks.audit import fetch_site_page

        async def fake_fetch(url: str, **kwargs: object) -> FetchedPage:
            raise FetchError("https://example.com/", "сервер не ответил вовремя")

        with patch("ads_os.worker.tasks.audit.fetch_page", fake_fetch):
            result = fetch_site_page("https://example.com/")

        assert result == {"ok": False, "reason": "сервер не ответил вовремя"}


class TestОбработкаЗадачи:
    async def test_успешный_аудит_сохраняет_оценку(
        self, session: AsyncSession, project_with_site: tuple[Organization, User, Project]
    ) -> None:
        from ads_os.worker.tasks.audit import _process

        audit = await _make_audit(session, project_with_site, ModuleStatus.QUEUED)

        result = await _process(audit.id, OK_FETCH)

        assert result == "completed"

        await session.refresh(audit)
        assert audit.status is ModuleStatus.COMPLETED
        assert audit.score is not None and audit.score > 0
        assert audit.metrica_counter == "99887766"
        assert audit.finished_at is not None
        # Категории и находки сохранились в виде, пригодном для интерфейса.
        assert len(audit.categories) == 5
        assert all("category" in c and "score" in c for c in audit.categories)

    async def test_недоступный_сайт_записывает_причину(
        self, session: AsyncSession, project_with_site: tuple[Organization, User, Project]
    ) -> None:
        """Наружу уходит понятная причина, а не текст исключения."""
        from ads_os.worker.tasks.audit import _process

        audit = await _make_audit(session, project_with_site, ModuleStatus.QUEUED)

        result = await _process(
            audit.id, {"ok": False, "reason": "сервер не ответил вовремя"}
        )

        assert result == "failed"
        await session.refresh(audit)
        assert audit.status is ModuleStatus.FAILED
        assert audit.error_reason == "сервер не ответил вовремя"

    async def test_повторный_запуск_задачи_не_переделывает_работу(
        self, session: AsyncSession, project_with_site: tuple[Organization, User, Project]
    ) -> None:
        """Очередь может доставить задачу дважды — это норма (v0.3 §33)."""
        from ads_os.worker.tasks.audit import _process

        audit = await _make_audit(session, project_with_site, ModuleStatus.COMPLETED, score=88)

        result = await _process(audit.id, OK_FETCH)

        assert result == "completed"
        await session.refresh(audit)
        # Прежняя оценка осталась нетронутой.
        assert audit.score == 88

    async def test_несуществующий_аудит_не_роняет_воркер(self) -> None:
        import uuid as uuid_module

        from ads_os.worker.tasks.audit import _process

        assert await _process(uuid_module.uuid4(), OK_FETCH) == "not_found"


class TestХранение:
    async def test_история_аудитов_сохраняется(
        self, session: AsyncSession, project_with_site: tuple[Organization, User, Project]
    ) -> None:
        """Нужно видеть, что менялось на сайте между запусками (v0.3 §62)."""
        org, _, project = project_with_site
        for _ in range(3):
            session.add(
                SiteAudit(
                    organization_id=org.id,
                    project_id=project.id,
                    url="https://example.com/",
                    status=ModuleStatus.COMPLETED,
                    categories=[],
                    issues=[],
                )
            )
        await session.commit()

        rows = (
            await session.execute(select(SiteAudit).where(SiteAudit.project_id == project.id))
        ).scalars().all()
        assert len(rows) == 3
