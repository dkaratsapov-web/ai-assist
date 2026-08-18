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
        status=status,
        # Значения по умолчанию, которые вызывающий может заменить своими.
        **{"url": "https://example.com/", "categories": [], "issues": [], **fields},
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


ISSUE_NO_PRICES = {
    "key": "no_prices",
    "category": "offer",
    "severity": "recommendation",
    "title": "На странице нет цен",
    "action": "Покажите цены или диапазон.",
}

ISSUE_NO_METRICA = {
    "key": "no_metrica",
    "category": "tracking",
    "severity": "critical",
    "title": "Не установлена Яндекс Метрика",
    "action": "Установите счётчик до запуска.",
}


class TestСкрытыеЗамечания:
    """Система знает, чего на сайте нет. Почему — знает только человек."""

    async def test_скрытое_замечание_помечается_а_не_исчезает(
        self,
        client: AsyncClient,
        session: AsyncSession,
        project_with_site: tuple[Organization, User, Project],
    ) -> None:
        org, user, project = project_with_site
        await _make_audit(
            session,
            project_with_site,
            ModuleStatus.COMPLETED,
            score=70,
            issues=[ISSUE_NO_PRICES],
        )

        await client.post(
            f"/api/v1/projects/{project.id}/audit/dismissals",
            json={"issue_key": "no_prices", "reason": "цены считаем индивидуально"},
            headers=headers(org, user),
        )

        body = (
            await client.get(
                f"/api/v1/projects/{project.id}/audit", headers=headers(org, user)
            )
        ).json()

        # Проверка по-прежнему находит это замечание — изменилось только то,
        # как оно показывается.
        assert len(body["issues"]) == 1
        assert body["issues"][0]["dismissed"] is True
        assert body["issues"][0]["dismissed_reason"] == "цены считаем индивидуально"

    async def test_балл_от_скрытия_не_меняется(
        self,
        client: AsyncClient,
        session: AsyncSession,
        project_with_site: tuple[Organization, User, Project],
    ) -> None:
        """Балл — это измерение, а не договорённость."""
        org, user, project = project_with_site
        await _make_audit(
            session,
            project_with_site,
            ModuleStatus.COMPLETED,
            score=70,
            issues=[ISSUE_NO_PRICES],
        )

        await client.post(
            f"/api/v1/projects/{project.id}/audit/dismissals",
            json={"issue_key": "no_prices"},
            headers=headers(org, user),
        )

        body = (
            await client.get(
                f"/api/v1/projects/{project.id}/audit", headers=headers(org, user)
            )
        ).json()

        assert body["score"] == 70

    async def test_критическое_замечание_скрыть_нельзя(
        self,
        client: AsyncClient,
        session: AsyncSession,
        project_with_site: tuple[Organization, User, Project],
    ) -> None:
        """Блокировка, которую можно спрятать, не является блокировкой."""
        org, user, project = project_with_site
        await _make_audit(
            session,
            project_with_site,
            ModuleStatus.COMPLETED,
            score=30,
            issues=[ISSUE_NO_METRICA],
        )

        response = await client.post(
            f"/api/v1/projects/{project.id}/audit/dismissals",
            json={"issue_key": "no_metrica"},
            headers=headers(org, user),
        )

        assert response.status_code == 422
        assert response.json()["error_code"] == "issue_is_blocking"

    async def test_несуществующая_проверка_отклоняется(
        self,
        client: AsyncClient,
        project_with_site: tuple[Organization, User, Project],
    ) -> None:
        org, user, project = project_with_site

        response = await client.post(
            f"/api/v1/projects/{project.id}/audit/dismissals",
            json={"issue_key": "выдуманная_проверка"},
            headers=headers(org, user),
        )

        assert response.status_code == 404

    async def test_повторное_скрытие_не_создаёт_второе_решение(
        self,
        client: AsyncClient,
        project_with_site: tuple[Organization, User, Project],
    ) -> None:
        org, user, project = project_with_site

        for reason in ("первая формулировка", "уточнённая формулировка"):
            await client.post(
                f"/api/v1/projects/{project.id}/audit/dismissals",
                json={"issue_key": "no_prices", "reason": reason},
                headers=headers(org, user),
            )

        body = (
            await client.get(
                f"/api/v1/projects/{project.id}/audit/dismissals", headers=headers(org, user)
            )
        ).json()

        assert body["total"] == 1
        assert body["items"][0]["reason"] == "уточнённая формулировка"

    async def test_замечание_возвращается_в_список(
        self,
        client: AsyncClient,
        project_with_site: tuple[Organization, User, Project],
    ) -> None:
        org, user, project = project_with_site
        await client.post(
            f"/api/v1/projects/{project.id}/audit/dismissals",
            json={"issue_key": "no_prices"},
            headers=headers(org, user),
        )

        response = await client.delete(
            f"/api/v1/projects/{project.id}/audit/dismissals/no_prices",
            headers=headers(org, user),
        )

        assert response.status_code == 204
        body = (
            await client.get(
                f"/api/v1/projects/{project.id}/audit/dismissals", headers=headers(org, user)
            )
        ).json()
        assert body["total"] == 0

    async def test_чужие_скрытия_недоступны(
        self,
        client: AsyncClient,
        session: AsyncSession,
        project_with_site: tuple[Organization, User, Project],
        two_organizations: tuple[Organization, Organization],
    ) -> None:
        _, _, project = project_with_site
        _, other_org = two_organizations
        other_user = await make_user(session, other_org, "other@example.com")
        await session.commit()

        response = await client.post(
            f"/api/v1/projects/{project.id}/audit/dismissals",
            json={"issue_key": "no_prices"},
            headers=headers(other_org, other_user),
        )

        assert response.status_code == 404


class TestНесколькоПосадочных:
    """В кампании посадочных обычно несколько, и оценивать все по главной —
    значит не проверять их вовсе."""

    async def test_проверка_другой_страницы_того_же_сайта(
        self, client: AsyncClient, project_with_site: tuple[Organization, User, Project]
    ) -> None:
        org, user, project = project_with_site

        with patch("ads_os.api.v1.audit.enqueue_site_audit"):
            response = await client.post(
                f"/api/v1/projects/{project.id}/audit",
                json={"url": "https://example.com/okna-pvh"},
                headers=headers(org, user),
            )

        assert response.status_code == 202
        assert response.json()["url"] == "https://example.com/okna-pvh"

    async def test_чужой_сайт_проверять_нельзя(
        self, client: AsyncClient, project_with_site: tuple[Organization, User, Project]
    ) -> None:
        """Иначе краулер гоняли бы по произвольным адресам от имени сервиса."""
        org, user, project = project_with_site

        response = await client.post(
            f"/api/v1/projects/{project.id}/audit",
            json={"url": "https://чужой-сайт.ru/страница"},
            headers=headers(org, user),
        )

        assert response.status_code == 422
        assert response.json()["error_code"] == "foreign_page"

    async def test_www_считается_тем_же_сайтом(
        self, client: AsyncClient, project_with_site: tuple[Organization, User, Project]
    ) -> None:
        """Требовать угадать написание было бы придиркой."""
        org, user, project = project_with_site

        with patch("ads_os.api.v1.audit.enqueue_site_audit"):
            response = await client.post(
                f"/api/v1/projects/{project.id}/audit",
                json={"url": "https://www.example.com/balkony"},
                headers=headers(org, user),
            )

        assert response.status_code == 202

    async def test_проверка_страницы_не_блокирует_другую(
        self,
        client: AsyncClient,
        session: AsyncSession,
        project_with_site: tuple[Organization, User, Project],
    ) -> None:
        """Идущая проверка главной не должна мешать проверить соседнюю."""
        org, user, project = project_with_site
        await _make_audit(session, project_with_site, ModuleStatus.RUNNING)

        with patch("ads_os.api.v1.audit.enqueue_site_audit"):
            response = await client.post(
                f"/api/v1/projects/{project.id}/audit",
                json={"url": "https://example.com/other"},
                headers=headers(org, user),
            )

        assert response.status_code == 202

    async def test_результат_запрашивается_по_адресу(
        self,
        client: AsyncClient,
        session: AsyncSession,
        project_with_site: tuple[Organization, User, Project],
    ) -> None:
        org, user, project = project_with_site
        await _make_audit(
            session, project_with_site, ModuleStatus.COMPLETED, score=90, url="https://example.com/"
        )
        await _make_audit(
            session,
            project_with_site,
            ModuleStatus.COMPLETED,
            score=40,
            url="https://example.com/other",
        )

        main = (
            await client.get(
                f"/api/v1/projects/{project.id}/audit", headers=headers(org, user)
            )
        ).json()
        other = (
            await client.get(
                f"/api/v1/projects/{project.id}/audit?url=https://example.com/other",
                headers=headers(org, user),
            )
        ).json()

        assert main["score"] == 90
        assert other["score"] == 40

    async def test_список_страниц_показывает_главную_даже_без_проверок(
        self, client: AsyncClient, project_with_site: tuple[Organization, User, Project]
    ) -> None:
        """Иначе у нового проекта список пуст и непонятно, с чего начать."""
        org, user, project = project_with_site

        body = (
            await client.get(
                f"/api/v1/projects/{project.id}/audit/pages", headers=headers(org, user)
            )
        ).json()

        assert body["total"] == 1
        assert body["items"][0]["is_primary"] is True
        assert body["items"][0]["status"] == "not_started"

    async def test_худшая_страница_идёт_первой_после_главной(
        self,
        client: AsyncClient,
        session: AsyncSession,
        project_with_site: tuple[Organization, User, Project],
    ) -> None:
        """Работать начинают с той страницы, которая тянет вниз."""
        org, user, project = project_with_site
        await _make_audit(
            session, project_with_site, ModuleStatus.COMPLETED, score=95, url="https://example.com/"
        )
        await _make_audit(
            session, project_with_site, ModuleStatus.COMPLETED, score=80, url="https://example.com/a"
        )
        await _make_audit(
            session, project_with_site, ModuleStatus.COMPLETED, score=30, url="https://example.com/b"
        )

        items = (
            await client.get(
                f"/api/v1/projects/{project.id}/audit/pages", headers=headers(org, user)
            )
        ).json()["items"]

        assert items[0]["is_primary"] is True
        assert items[1]["score"] == 30
        assert items[2]["score"] == 80


class TestРазборМоделью:
    """Мнение модели отдаётся вместе с проверкой, но живёт отдельно от неё."""

    async def test_мнение_приходит_с_результатом(
        self,
        client: AsyncClient,
        session: AsyncSession,
        project_with_site: tuple[Organization, User, Project],
    ) -> None:
        org, user, project = project_with_site
        await _make_audit(
            session,
            project_with_site,
            ModuleStatus.COMPLETED,
            score=80,
            review={
                "available": True,
                "summary": "Предложение понятное, но цена без условий.",
                "strongest": "Гарантия на первом экране.",
                "weakest": "Не сказано, что входит в цену.",
                "confidence": 0.7,
                "model": "модель-1",
                "notes": [
                    {
                        "topic": "offer",
                        "grade": "weak",
                        "what": "Цена без состава работ.",
                        "fix": "Показать, что входит.",
                        "quote": "от 350 рублей за метр",
                    }
                ],
            },
        )

        body = (
            await client.get(f"/api/v1/projects/{project.id}/audit", headers=headers(org, user))
        ).json()

        assert body["review"]["available"] is True
        assert body["review"]["notes"][0]["quote"] == "от 350 рублей за метр"

    async def test_старые_проверки_объясняют_отсутствие_разбора(
        self,
        client: AsyncClient,
        session: AsyncSession,
        project_with_site: tuple[Organization, User, Project],
    ) -> None:
        """Пустой блок человек читает как поломку, а не как «разбора не было»."""
        org, user, project = project_with_site
        await _make_audit(session, project_with_site, ModuleStatus.COMPLETED, score=80)

        body = (
            await client.get(f"/api/v1/projects/{project.id}/audit", headers=headers(org, user))
        ).json()

        assert body["review"]["available"] is False
        assert body["review"]["reason"]

    async def test_мнение_не_влияет_на_возможность_запуска(
        self,
        client: AsyncClient,
        session: AsyncSession,
        project_with_site: tuple[Organization, User, Project],
    ) -> None:
        """Модель ошибается, и её ошибка не должна запрещать запуск."""
        org, user, project = project_with_site
        await _make_audit(
            session,
            project_with_site,
            ModuleStatus.COMPLETED,
            score=95,
            issues=[],
            review={
                "available": True,
                "summary": "Страница никуда не годится.",
                "strongest": "",
                "weakest": "Всё плохо.",
                "confidence": 0.9,
                "model": "модель-1",
                "notes": [
                    {
                        "topic": "offer",
                        "grade": "missing",
                        "what": "Предложения нет.",
                        "fix": "Написать предложение.",
                        "quote": "",
                    }
                ],
            },
        )

        body = (
            await client.get(f"/api/v1/projects/{project.id}/audit", headers=headers(org, user))
        ).json()

        assert body["can_launch"] is True
        assert body["score"] == 95
