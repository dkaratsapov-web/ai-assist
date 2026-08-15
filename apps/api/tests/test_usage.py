"""Учёт потребления.

Проверяется то, ради чего он существует: цифры невозможно восстановить задним
числом, а лимит должен останавливать работу до её начала, а не после.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from ads_os.db.base import utcnow
from ads_os.models import Organization, Project
from ads_os.models.organization import OrganizationPlan
from ads_os.models.usage import UsageEvent, UsageService, UsageUnit
from ads_os.services.usage import (
    USAGE_WINDOW,
    crawler_limit_reached,
    record,
    summarize,
)


async def add_pages(
    session: AsyncSession, org: Organization, count: int, *, age: timedelta = timedelta()
) -> None:
    for _ in range(count):
        event = UsageEvent(
            organization_id=org.id,
            service=UsageService.CRAWLER,
            operation="site_audit",
            quantity=1,
            unit=UsageUnit.PAGES,
        )
        event.created_at = utcnow() - age
        session.add(event)
    await session.flush()


class TestЗапись:
    async def test_потребление_записывается(
        self, session: AsyncSession, two_organizations: tuple[Organization, Organization]
    ) -> None:
        org, _ = two_organizations
        project = Project(organization_id=org.id, name="Проект")
        session.add(project)
        await session.flush()

        await record(
            session,
            organization_id=org.id,
            service=UsageService.CRAWLER,
            operation="site_audit",
            quantity=1,
            unit=UsageUnit.PAGES,
            project_id=project.id,
        )
        await session.commit()

        summary = await summarize(session, org.id)
        assert summary.crawler_pages == 1

    async def test_чужое_потребление_не_считается(
        self, session: AsyncSession, two_organizations: tuple[Organization, Organization]
    ) -> None:
        org, other = two_organizations
        await add_pages(session, other, 5)
        await session.commit()

        summary = await summarize(session, org.id)
        assert summary.crawler_pages == 0

    async def test_старое_потребление_выпадает_из_окна(
        self, session: AsyncSession, two_organizations: tuple[Organization, Organization]
    ) -> None:
        """Окно скользящее: иначе на стыке месяцев тратится двойная норма."""
        org, _ = two_organizations
        await add_pages(session, org, 3)
        await add_pages(session, org, 10, age=USAGE_WINDOW + timedelta(days=1))
        await session.commit()

        summary = await summarize(session, org.id)
        assert summary.crawler_pages == 3


class TestЛимит:
    async def test_лимит_останавливает_работу(
        self, session: AsyncSession, two_organizations: tuple[Organization, Organization]
    ) -> None:
        org, _ = two_organizations
        session.add(OrganizationPlan(organization_id=org.id, crawler_pages_limit=5))
        await add_pages(session, org, 5)
        await session.commit()

        assert await crawler_limit_reached(session, org.id) is True

    async def test_до_лимита_работа_идёт(
        self, session: AsyncSession, two_organizations: tuple[Organization, Organization]
    ) -> None:
        org, _ = two_organizations
        session.add(OrganizationPlan(organization_id=org.id, crawler_pages_limit=5))
        await add_pages(session, org, 4)
        await session.commit()

        assert await crawler_limit_reached(session, org.id) is False

    async def test_без_плана_лимита_нет(
        self, session: AsyncSession, two_organizations: tuple[Organization, Organization]
    ) -> None:
        """Отсутствие тарифа не должно превращаться в запрет работы."""
        org, _ = two_organizations
        await add_pages(session, org, 10_000)
        await session.commit()

        assert await crawler_limit_reached(session, org.id) is False

    async def test_доля_не_делится_на_ноль(
        self, session: AsyncSession, two_organizations: tuple[Organization, Organization]
    ) -> None:
        org, _ = two_organizations
        await session.commit()

        summary = await summarize(session, org.id)
        assert summary.crawler_share == 0.0


class TestУстойчивость:
    async def test_длинные_значения_обрезаются_а_не_рвут_транзакцию(
        self, session: AsyncSession, two_organizations: tuple[Organization, Organization]
    ) -> None:
        """Неудачная запись порвала бы всю транзакцию, а не только эту строку.

        Вместе со строкой статистики пропала бы сама проверка сайта — цена,
        несоразмерная поводу. Поэтому запись сделана такой, что не может не
        пройти.
        """
        org, _ = two_organizations

        await record(
            session,
            organization_id=org.id,
            service=UsageService.CRAWLER,
            operation="x" * 500,
            quantity=1,
            unit=UsageUnit.PAGES,
            meta={"url": "y" * 900},
        )
        await session.commit()

        summary = await summarize(session, org.id)
        assert summary.crawler_pages == 1

    async def test_после_записи_сессия_пригодна(
        self, session: AsyncSession, two_organizations: tuple[Organization, Organization]
    ) -> None:
        """Ради этого запись и не может падать: работа продолжается после неё."""
        org, _ = two_organizations

        await record(
            session,
            organization_id=org.id,
            service=UsageService.CRAWLER,
            operation="site_audit",
            quantity=1,
            unit=UsageUnit.PAGES,
        )
        project = Project(organization_id=org.id, name="После учёта")
        session.add(project)
        await session.commit()

        assert project.id is not None
