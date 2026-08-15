"""Фоновый разбор конкурента."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from ads_os.models import Competitor, Organization, Project, User
from ads_os.models.audit import ModuleStatus
from ads_os.worker.tasks.competitors import MAX_TITLE_LENGTH, _process

from .conftest import make_user

PAGE = """
<html><head><title>Конкурент — ремонт техники в Твери</title>
<meta name="viewport" content="width=device-width"></head>
<body><h1>Ремонт за час</h1><p>от 2 900 ₽, гарантия 6 месяцев</p>
<form><input name="phone"><button>Заказать</button></form></body></html>
"""

OK_FETCH = {"ok": True, "final_url": "https://rival.ru/", "status_code": 200, "html": PAGE}


@pytest.fixture
async def rival(
    session: AsyncSession, two_organizations: tuple[Organization, Organization]
) -> AsyncIterator[Competitor]:
    org, _ = two_organizations
    user: User = await make_user(session, org, "u@example.com")
    project = Project(organization_id=org.id, name="Проект", created_by_id=user.id)
    session.add(project)
    await session.flush()

    competitor = Competitor(
        organization_id=org.id,
        project_id=project.id,
        url="https://rival.ru/",
        status=ModuleStatus.QUEUED,
        features={},
    )
    session.add(competitor)
    await session.commit()
    yield competitor


class TestРазбор:
    async def test_признаки_сохраняются(
        self, session: AsyncSession, rival: Competitor
    ) -> None:
        assert await _process(rival.id, OK_FETCH) == "completed"

        await session.refresh(rival)
        assert rival.status is ModuleStatus.COMPLETED
        assert rival.features["form"] is True
        assert rival.features["prices"] is True
        # Счётчика Метрики на странице нет — и это должно быть видно.
        assert rival.features["analytics"] is False
        assert rival.checked_at is not None

    async def test_заголовок_берётся_со_страницы(
        self, session: AsyncSession, rival: Competitor
    ) -> None:
        await _process(rival.id, OK_FETCH)

        await session.refresh(rival)
        assert rival.title is not None
        assert "Конкурент" in rival.title
        assert len(rival.title) <= MAX_TITLE_LENGTH

    async def test_своё_название_не_затирается(
        self, session: AsyncSession, rival: Competitor
    ) -> None:
        """Пользователь писал название для себя и по нему узнаёт конкурента."""
        rival.title = "Тот, что через дорогу"
        await session.commit()

        await _process(rival.id, OK_FETCH)

        await session.refresh(rival)
        assert rival.title == "Тот, что через дорогу"

    async def test_недоступный_сайт_записывает_причину(
        self, session: AsyncSession, rival: Competitor
    ) -> None:
        result = await _process(rival.id, {"ok": False, "reason": "сервер не ответил вовремя"})

        assert result == "failed"
        await session.refresh(rival)
        assert rival.status is ModuleStatus.FAILED
        assert rival.error_reason == "сервер не ответил вовремя"

    async def test_повторный_разбор_очищает_прежнюю_ошибку(
        self, session: AsyncSession, rival: Competitor
    ) -> None:
        """Иначе рядом с успешным результатом висела бы старая причина сбоя."""
        rival.status = ModuleStatus.FAILED
        rival.error_reason = "сервер не ответил вовремя"
        await session.commit()

        await _process(rival.id, OK_FETCH)

        await session.refresh(rival)
        assert rival.status is ModuleStatus.COMPLETED
        assert rival.error_reason is None

    async def test_несуществующий_конкурент_не_роняет_воркер(self) -> None:
        import uuid

        assert await _process(uuid.uuid4(), OK_FETCH) == "not_found"
