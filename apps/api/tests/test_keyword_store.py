"""Запись фраз в ядро проекта.

Путей записи два — человек вставляет выгрузку и сборщик приносит фразы из
Вордстата, — а правила слияния обязаны быть общими. Здесь проверяются именно
они: что фраза не двоится, что ручное решение переживает следующий сбор и что
частотность обновляется.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ads_os.models import Keyword, MinusWord, Organization, Project
from ads_os.services import keyword_store
from ads_os.services.keyword_store import Phrase
from ads_os.services.semantics import Intent

from .conftest import make_project


@pytest.fixture
async def project(
    session: AsyncSession, two_organizations: tuple[Organization, Organization]
) -> tuple[Organization, Project]:
    org, _ = two_organizations
    item = await make_project(session, org, "Окна")
    await session.commit()
    return org, item


async def store(
    session: AsyncSession,
    org: Organization,
    project: Project,
    phrases: list[Phrase],
    **kwargs: object,
) -> keyword_store.StoreResult:
    return await keyword_store.upsert(
        session,
        phrases,
        organization_id=org.id,
        project_id=project.id,
        **kwargs,  # type: ignore[arg-type]
    )


async def rows(session: AsyncSession, project: Project) -> list[Keyword]:
    return list(
        (await session.execute(select(Keyword).where(Keyword.project_id == project.id)))
        .scalars()
        .all()
    )


class TestЗапись:
    async def test_новые_фразы_добавляются(
        self, session: AsyncSession, project: tuple[Organization, Project]
    ) -> None:
        org, item = project

        result = await store(
            session, org, item, [Phrase("пластиковые окна", 5400), Phrase("окна пвх", 1200)]
        )

        assert result.added == 2
        assert {r.phrase for r in await rows(session, item)} == {"пластиковые окна", "окна пвх"}

    async def test_фраза_не_двоится(
        self, session: AsyncSession, project: tuple[Organization, Project]
    ) -> None:
        """Иначе ядро росло бы с каждым сбором, а частотности расходились бы
        между дублями."""
        org, item = project
        await store(session, org, item, [Phrase("пластиковые окна", 5400)])

        result = await store(session, org, item, [Phrase("пластиковые окна", 5600)])

        assert result.added == 0
        assert result.updated == 1
        assert len(await rows(session, item)) == 1

    async def test_частотность_обновляется(
        self, session: AsyncSession, project: tuple[Organization, Project]
    ) -> None:
        """Устаревшее число хуже отсутствующего: по нему считают бюджет."""
        org, item = project
        await store(session, org, item, [Phrase("пластиковые окна", 5400)])

        await store(session, org, item, [Phrase("пластиковые окна", 9100)])

        assert (await rows(session, item))[0].frequency == 9100

    async def test_пустая_частотность_не_стирает_известную(
        self, session: AsyncSession, project: tuple[Organization, Project]
    ) -> None:
        """None означает «не измеряли», а не «ноль»."""
        org, item = project
        await store(session, org, item, [Phrase("пластиковые окна", 5400)])

        await store(session, org, item, [Phrase("пластиковые окна", None)])

        assert (await rows(session, item))[0].frequency == 5400

    async def test_пробелы_и_регистр_сводятся(
        self, session: AsyncSession, project: tuple[Organization, Project]
    ) -> None:
        """«Пластиковые  Окна» и «пластиковые окна» — одна фраза, и две записи
        о ней означали бы двойной подсчёт охвата."""
        org, item = project
        await store(session, org, item, [Phrase("пластиковые окна", 100)])

        await store(session, org, item, [Phrase("  Пластиковые   Окна ", 200)])

        assert len(await rows(session, item)) == 1

    async def test_пустая_строка_пропускается(
        self, session: AsyncSession, project: tuple[Organization, Project]
    ) -> None:
        org, item = project

        result = await store(session, org, item, [Phrase("   ", 10), Phrase("окна", 20)])

        assert result.added == 1


class TestРучныеРешения:
    async def test_ручная_разметка_переживает_сбор(
        self, session: AsyncSession, project: tuple[Organization, Project]
    ) -> None:
        """Разметка, которая отменяется сама, — это разметка, которой не
        доверяют, и делать её перестают."""
        org, item = project
        await store(session, org, item, [Phrase("пластиковые окна", 100)])
        row = (await rows(session, item))[0]
        row.intent = Intent.IRRELEVANT
        row.is_manual = True
        await session.flush()

        await store(session, org, item, [Phrase("пластиковые окна", 200)])

        assert (await rows(session, item))[0].intent is Intent.IRRELEVANT

    async def test_частотность_обновляется_и_у_ручных(
        self, session: AsyncSession, project: tuple[Organization, Project]
    ) -> None:
        """Число приходит от площадки и от мнения человека не зависит."""
        org, item = project
        await store(session, org, item, [Phrase("пластиковые окна", 100)])
        row = (await rows(session, item))[0]
        row.is_manual = True
        await session.flush()

        await store(session, org, item, [Phrase("пластиковые окна", 777)])

        assert (await rows(session, item))[0].frequency == 777


class TestРазбор:
    async def test_минус_слово_делает_фразу_нецелевой(
        self, session: AsyncSession, project: tuple[Organization, Project]
    ) -> None:
        org, item = project
        session.add(
            MinusWord(organization_id=org.id, project_id=item.id, word="вакансии")
        )
        await session.flush()

        await store(
            session,
            org,
            item,
            [Phrase("окна вакансии", 50)],
            extra_irrelevant=await keyword_store.minus_words(session, project_id=item.id),
        )

        assert (await rows(session, item))[0].intent is Intent.IRRELEVANT

    async def test_чужой_город_отсекается_по_региону(
        self, session: AsyncSession, project: tuple[Organization, Project]
    ) -> None:
        """Фраза с чужим городом — это не спрос клиента, а трафик соседнего
        рынка, и платить за него нечем."""
        org, item = project

        await store(session, org, item, [Phrase("пластиковые окна казань", 300)], region="Тверь")

        assert (await rows(session, item))[0].intent is Intent.IRRELEVANT


class TestГруппировка:
    async def test_фразы_раскладываются_по_группам(
        self, session: AsyncSession, project: tuple[Organization, Project]
    ) -> None:
        org, item = project
        await store(
            session,
            org,
            item,
            [
                Phrase("пластиковые окна тверь", 5400),
                Phrase("купить пластиковые окна", 3100),
                Phrase("пластиковые окна цена", 2800),
            ],
        )

        groups = await keyword_store.recluster(session, project_id=item.id)

        assert groups >= 1
        assert all(r.cluster_name for r in await rows(session, item))

    async def test_нецелевые_в_группы_не_идут(
        self, session: AsyncSession, project: tuple[Organization, Project]
    ) -> None:
        """Группа собирается под объявление, а по нецелевым фразам объявлений
        не делают."""
        org, item = project
        await store(
            session,
            org,
            item,
            [Phrase("пластиковые окна тверь", 5400), Phrase("пластиковые окна казань", 300)],
            region="Тверь",
        )

        await keyword_store.recluster(session, project_id=item.id)

        stray = next(r for r in await rows(session, item) if "казань" in r.phrase)
        assert stray.cluster_name is None


class TestРучныеГруппы:
    """Пересчёт не должен стирать раскладку, сделанную руками."""

    async def test_ручная_группа_переживает_пересчёт(
        self, session: AsyncSession, project: tuple[Organization, Project]
    ) -> None:
        org, item = project
        await store(
            session,
            org,
            item,
            [Phrase("пластиковые окна тверь", 5400), Phrase("купить пластиковые окна", 3100)],
        )
        row = (await rows(session, item))[0]
        await keyword_store.move_to_group(
            session, [row.id], project_id=item.id, group="Своя группа"
        )

        await keyword_store.recluster(session, project_id=item.id)

        assert (await rows(session, item))[0].cluster_name == "Своя группа"

    async def test_остальные_фразы_пересчёт_трогает(
        self, session: AsyncSession, project: tuple[Organization, Project]
    ) -> None:
        """Иначе одна ручная правка заморозила бы всю структуру."""
        org, item = project
        await store(
            session,
            org,
            item,
            [Phrase("пластиковые окна тверь", 5400), Phrase("купить пластиковые окна", 3100)],
        )
        first = (await rows(session, item))[0]
        await keyword_store.move_to_group(
            session, [first.id], project_id=item.id, group="Своя группа"
        )

        await keyword_store.recluster(session, project_id=item.id)

        others = [r for r in await rows(session, item) if r.id != first.id]
        assert all(r.cluster_name and r.cluster_name != "Своя группа" for r in others)

    async def test_роспуск_возвращает_фразы_расчёту(
        self, session: AsyncSession, project: tuple[Organization, Project]
    ) -> None:
        org, item = project
        await store(session, org, item, [Phrase("пластиковые окна тверь", 5400)])
        row = (await rows(session, item))[0]
        await keyword_store.move_to_group(session, [row.id], project_id=item.id, group="Своя")

        await keyword_store.dissolve_group(session, project_id=item.id, name="Своя")
        await keyword_store.recluster(session, project_id=item.id)

        after = (await rows(session, item))[0]
        assert after.cluster_manual is False
        assert after.cluster_name != "Своя"

    async def test_нецелевая_фраза_вылетает_из_группы_даже_ручной(
        self, session: AsyncSession, project: tuple[Organization, Project]
    ) -> None:
        """Раз фраза признана нецелевой, объявления по ней не будет — и место
        в структуре она занимать не должна."""
        org, item = project
        await store(session, org, item, [Phrase("пластиковые окна тверь", 5400)])
        row = (await rows(session, item))[0]
        await keyword_store.move_to_group(session, [row.id], project_id=item.id, group="Своя")
        row.intent = Intent.IRRELEVANT
        row.is_manual = True
        await session.flush()

        await keyword_store.recluster(session, project_id=item.id)

        assert (await rows(session, item))[0].cluster_name is None
