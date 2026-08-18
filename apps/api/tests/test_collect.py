"""Сбор частотностей по маскам.

Всё здесь проверяется вокруг одного числа — сто запросов в час на весь сервис.
Из него следует главное свойство сбора: он обязан переживать перерыв. Уже
добытые фразы оплачены запросами, и потерять их значит потратить квоту дважды.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ads_os.models import Keyword, KeywordCollection, Organization, Project
from ads_os.models.audit import ModuleStatus
from ads_os.models.semantics import KeywordBrief
from ads_os.services.wordstat_api import NullSource, Phrase, TopResult, WordstatError
from ads_os.services.wordstat_quota import MemoryQuota
from ads_os.worker.tasks import collect

from .conftest import make_project


@pytest.fixture
async def project(
    session: AsyncSession, two_organizations: tuple[Organization, Organization]
) -> tuple[Organization, Project]:
    org, _ = two_organizations
    item = await make_project(session, org, "Окна")
    item.primary_region = "Тверь"
    await session.commit()
    return org, item


async def make_collection(
    session: AsyncSession,
    org: Organization,
    project: Project,
    queries: list[str],
) -> KeywordCollection:
    row = KeywordCollection(
        organization_id=org.id,
        project_id=project.id,
        masks=[
            {"query": q, "purpose": "", "state": collect.PENDING, "reason": ""} for q in queries
        ],
    )
    session.add(row)
    await session.commit()
    return row


class Source:
    """Вордстат, отвечающий заранее заданным."""

    def __init__(self, answers: dict[str, object]) -> None:
        self.answers = answers
        self.asked: list[str] = []

    async def top(self, phrase: str, *, regions: tuple[str, ...] = (), num_phrases: int = 500):
        self.asked.append(phrase)
        answer = self.answers.get(phrase)
        if isinstance(answer, Exception):
            raise answer
        return answer or TopResult(total=0)


def result(*phrases: tuple[str, int]) -> TopResult:
    return TopResult(
        total=sum(count for _, count in phrases),
        results=tuple(Phrase(phrase=text, count=count) for text, count in phrases),
    )


def run(source: object, quota: object = None):
    """Подменяет источник и счётчик квоты на время одного прогона."""
    return (
        patch.object(collect.wordstat_api, "get_source", return_value=source),
        patch.object(collect.wordstat_quota, "get_quota", return_value=quota or MemoryQuota()),
        # apply_async — обычный метод, не корутина: AsyncMock оставил бы
        # неожидаемую корутину и предупреждение в каждом прогоне.
        patch.object(collect.collect_frequencies, "apply_async", MagicMock()),
        patch.object(collect.asyncio, "sleep", AsyncMock()),
    )


async def go(collection: KeywordCollection, source: object, quota: object = None) -> str:
    patches = run(source, quota)
    for item in patches:
        item.start()
    try:
        return await collect._collect(collection.id)
    finally:
        for item in patches:
            item.stop()


async def phrases_of(session: AsyncSession, project: Project) -> dict[str, int | None]:
    rows = (
        await session.execute(select(Keyword).where(Keyword.project_id == project.id))
    ).scalars()
    return {row.phrase: row.frequency for row in rows}


class TestСбор:
    async def test_фразы_попадают_в_ядро(
        self, session: AsyncSession, project: tuple[Organization, Project]
    ) -> None:
        org, item = project
        collection = await make_collection(session, org, item, ["пластиковые окна"])
        source = Source(
            {"пластиковые окна": result(("пластиковые окна тверь", 5400), ("окна пвх", 1200))}
        )

        await go(collection, source)

        assert await phrases_of(session, item) == {
            "пластиковые окна тверь": 5400,
            "окна пвх": 1200,
        }

    async def test_маски_отмечаются_по_одной(
        self, session: AsyncSession, project: tuple[Organization, Project]
    ) -> None:
        org, item = project
        collection = await make_collection(session, org, item, ["окна", "балконы"])
        source = Source({"окна": result(("окна тверь", 100)), "балконы": result(("балкон", 50))})

        await go(collection, source)
        await session.refresh(collection)

        assert [m["state"] for m in collection.masks] == [collect.DONE, collect.DONE]
        assert collection.status is ModuleStatus.COMPLETED

    async def test_итоги_считаются(
        self, session: AsyncSession, project: tuple[Organization, Project]
    ) -> None:
        org, item = project
        collection = await make_collection(session, org, item, ["окна"])
        source = Source({"окна": result(("окна тверь", 100), ("окна пвх", 50))})

        await go(collection, source)
        await session.refresh(collection)

        assert collection.added == 2
        assert collection.requests == 1

    async def test_базовая_частотность_маски_сохраняется(
        self, session: AsyncSession, project: tuple[Organization, Project]
    ) -> None:
        """По ней виден объём темы целиком, а не только собранного хвоста."""
        org, item = project
        collection = await make_collection(session, org, item, ["окна"])

        await go(collection, Source({"окна": result(("окна тверь", 100))}))
        await session.refresh(collection)

        assert collection.masks[0]["total"] == 100
        assert collection.masks[0]["found"] == 1

    async def test_фразы_раскладываются_по_группам(
        self, session: AsyncSession, project: tuple[Organization, Project]
    ) -> None:
        org, item = project
        collection = await make_collection(session, org, item, ["пластиковые окна"])
        source = Source(
            {
                "пластиковые окна": result(
                    ("пластиковые окна тверь", 5400),
                    ("купить пластиковые окна", 3100),
                    ("пластиковые окна цена", 2800),
                )
            }
        )

        await go(collection, source)

        rows = (
            await session.execute(select(Keyword).where(Keyword.project_id == item.id))
        ).scalars()
        assert all(row.cluster_name for row in rows)


class TestКвота:
    async def test_кончившаяся_квота_ставит_на_паузу_а_не_валит(
        self, session: AsyncSession, project: tuple[Organization, Project]
    ) -> None:
        """Показать «сбор не удался» там, где надо подождать сорок минут,
        значит заставить человека нажать «повторить» и потратить ещё запросов."""
        org, item = project
        collection = await make_collection(session, org, item, ["окна", "балконы"])
        source = Source({"окна": result(("окна тверь", 100))})

        outcome = await go(collection, source, quota=MemoryQuota(limit=1))
        await session.refresh(collection)

        assert outcome == "paused"
        assert collection.status is ModuleStatus.RUNNING
        assert collection.error_reason is None
        assert collection.resumes_at is not None

    async def test_собранное_до_паузы_сохраняется(
        self, session: AsyncSession, project: tuple[Organization, Project]
    ) -> None:
        """Уже добытые фразы оплачены запросами: терять их — платить дважды."""
        org, item = project
        collection = await make_collection(session, org, item, ["окна", "балконы"])
        source = Source({"окна": result(("окна тверь", 100))})

        await go(collection, source, quota=MemoryQuota(limit=1))

        assert "окна тверь" in await phrases_of(session, item)

    async def test_после_паузы_сбор_не_идёт_по_второму_кругу(
        self, session: AsyncSession, project: tuple[Organization, Project]
    ) -> None:
        """Собранная маска не должна тратить квоту снова."""
        org, item = project
        collection = await make_collection(session, org, item, ["окна", "балконы"])
        first = Source({"окна": result(("окна тверь", 100))})
        await go(collection, first, quota=MemoryQuota(limit=1))

        second = Source({"балконы": result(("балкон тверь", 50))})
        await go(collection, second)

        assert second.asked == ["балконы"]

    async def test_квота_тратится_по_запросу_на_маску(
        self, session: AsyncSession, project: tuple[Organization, Project]
    ) -> None:
        org, item = project
        collection = await make_collection(session, org, item, ["окна", "балконы", "двери"])
        quota = MemoryQuota(limit=10)

        await go(collection, Source({}), quota=quota)

        assert await quota.remaining() == 7


class TestОтказы:
    async def test_неподключённый_источник_объясняет_себя(
        self, session: AsyncSession, project: tuple[Organization, Project]
    ) -> None:
        org, item = project
        collection = await make_collection(session, org, item, ["окна"])

        await go(collection, NullSource())
        await session.refresh(collection)

        assert collection.status is ModuleStatus.FAILED
        assert "не подключён" in (collection.error_reason or "")

    async def test_повторяемый_отказ_площадки_ставит_на_паузу(
        self, session: AsyncSession, project: tuple[Organization, Project]
    ) -> None:
        org, item = project
        collection = await make_collection(session, org, item, ["окна"])
        source = Source({"окна": WordstatError("площадка не отвечает", retryable=True)})

        outcome = await go(collection, source)
        await session.refresh(collection)

        assert outcome == "paused"
        # Маска остаётся невыполненной: её возьмут при следующем заходе.
        assert collection.masks[0]["state"] == collect.PENDING

    async def test_неповторяемый_отказ_не_останавливает_остальные(
        self, session: AsyncSession, project: tuple[Organization, Project]
    ) -> None:
        """Одна кривая маска не должна отменять сбор целиком."""
        org, item = project
        collection = await make_collection(session, org, item, ["плохая", "окна"])
        source = Source(
            {
                "плохая": WordstatError("маска отклонена"),
                "окна": result(("окна тверь", 100)),
            }
        )

        await go(collection, source)
        await session.refresh(collection)

        assert [m["state"] for m in collection.masks] == [collect.FAILED, collect.DONE]
        assert collection.status is ModuleStatus.COMPLETED

    async def test_повторная_доставка_задачи_не_переделывает_работу(
        self, session: AsyncSession, project: tuple[Organization, Project]
    ) -> None:
        """Очередь может доставить задачу дважды — это норма (v0.3 §33)."""
        org, item = project
        collection = await make_collection(session, org, item, ["окна"])
        await go(collection, Source({"окна": result(("окна тверь", 100))}))

        second = Source({"окна": result(("окна тверь", 999))})
        await go(collection, second)

        assert second.asked == []


class TestМаски:
    def test_маски_строятся_из_брифа(self) -> None:
        project = Project(name="Окна", primary_region="Тверь")
        brief = KeywordBrief(sells="пластиковые окна", synonyms="", excludes="", cities="")

        built = collect.build_masks(project, brief)

        assert built
        assert all(m["state"] == collect.PENDING for m in built)
        assert any("пластиковые окна" in m["query"] for m in built)

    def test_без_брифа_собирать_нечего(self) -> None:
        """Маска из пустоты — это запрос ни о чём, потраченный из сотни в час."""
        assert collect.build_masks(Project(name="Окна"), None) == []
