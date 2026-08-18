"""Запись фраз в ядро проекта.

Вынесено из обработчика загрузки, потому что путей записи стало два: человек
вставляет выгрузку руками, а сборщик приносит фразы из Вордстата. Разбор,
классификация и правила слияния у них обязаны совпадать — иначе одна и та же
фраза, пришедшая двумя дорогами, получит разный тип, и человек увидит, что
система сама себе противоречит.

Правила слияния здесь одни и те же для обоих путей:

**Фраза в проекте существует один раз.** Повторное поступление обновляет её, а
не создаёт вторую копию: иначе ядро росло бы с каждым сбором, а частотности
расходились бы между дублями.

**Ручное решение не перетирается.** Если специалист отнёс фразу к нецелевым,
следующий сбор не вернёт её обратно. Разметка, которая отменяется сама, —
это разметка, которой не доверяют, и делать её перестают.

**Частотность обновляется всегда.** Она приходит от площадки и от мнения
человека не зависит; устаревшее число хуже отсутствующего, потому что по нему
считают бюджет.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Keyword, MinusWord
from .semantics import Intent, ParsedKeyword, classify, cluster


@dataclass(frozen=True, slots=True)
class Phrase:
    """Фраза и сколько раз её искали. `frequency=None` — «не измеряли»."""

    text: str
    frequency: int | None = None


@dataclass(frozen=True, slots=True)
class StoreResult:
    added: int = 0
    updated: int = 0

    @property
    def total(self) -> int:
        return self.added + self.updated


async def minus_words(
    session: AsyncSession, *, project_id: uuid.UUID
) -> frozenset[str]:
    """Минус-слова проекта. Участвуют в разборе: фраза с минус-словом нецелевая."""
    rows = (
        await session.execute(select(MinusWord.word).where(MinusWord.project_id == project_id))
    ).scalars()
    return frozenset(rows)


async def upsert(
    session: AsyncSession,
    phrases: Iterable[Phrase],
    *,
    organization_id: uuid.UUID,
    project_id: uuid.UUID,
    region: str | None = None,
    extra_irrelevant: frozenset[str] = frozenset(),
) -> StoreResult:
    """Добавляет фразы в ядро проекта, обновляя уже известные."""
    existing = {
        row.phrase: row
        for row in (
            await session.execute(select(Keyword).where(Keyword.project_id == project_id))
        )
        .scalars()
        .all()
    }

    added = updated = 0

    for item in phrases:
        text = " ".join(item.text.split()).strip().lower()
        if not text:
            continue

        row = existing.get(text)

        if row is None:
            result = classify(text, extra_irrelevant=extra_irrelevant, region=region)
            row = Keyword(
                organization_id=organization_id,
                project_id=project_id,
                phrase=text,
                frequency=item.frequency,
                intent=result.intent,
                trigger=result.trigger,
            )
            session.add(row)
            existing[text] = row
            added += 1
            continue

        if item.frequency is not None:
            row.frequency = item.frequency
        if not row.is_manual:
            result = classify(text, extra_irrelevant=extra_irrelevant, region=region)
            row.intent = result.intent
            row.trigger = result.trigger
        updated += 1

    await session.flush()
    return StoreResult(added=added, updated=updated)


async def recluster(session: AsyncSession, *, project_id: uuid.UUID) -> int:
    """Перекладывает фразы проекта по группам. Возвращает число групп.

    Делается после записи, а не во время: группировка смотрит на ядро целиком,
    и пересчитывать её после каждой фразы значило бы делать одну и ту же работу
    сотни раз подряд, получая осмысленный результат только на последнем шаге.

    Фразы, которые человек разложил руками, пересчёт не трогает. Это главное
    свойство здесь: без него специалист переносил бы фразу, а следующий сбор
    возвращал её обратно — редактирование, которое отменяется само, хуже
    отсутствующего, потому что на него тратят время впустую.
    """
    rows = list(
        (await session.execute(select(Keyword).where(Keyword.project_id == project_id)))
        .scalars()
        .all()
    )

    # Нецелевые в группы не идут: группа собирается под объявление, а по
    # нецелевым фразам объявлений не делают.
    automatic = [
        row for row in rows if row.intent is not Intent.IRRELEVANT and not row.cluster_manual
    ]
    groups = cluster([ParsedKeyword(row.phrase, row.frequency) for row in automatic])

    by_phrase = {phrase: group.name for group in groups for phrase in group.phrases}
    for row in automatic:
        row.cluster_name = by_phrase.get(row.phrase)

    # Нецелевые вычищаются из групп всегда, даже если группу им назначили
    # руками: раз фраза признана нецелевой, объявления по ней не будет.
    for row in rows:
        if row.intent is Intent.IRRELEVANT:
            row.cluster_name = None

    await session.flush()

    # Считаем по факту, а не по числу пересчитанных: ручные группы — тоже
    # группы, и не показать их значило бы соврать про размер структуры.
    return len({row.cluster_name for row in rows if row.cluster_name})


#: Название для фраз, оставшихся без группы. Показывается как обычная группа,
#: но объявления по ней не собираются: это не тема, а остаток.
UNGROUPED = "Остальные фразы"

MAX_GROUP_NAME = 200


@dataclass(frozen=True, slots=True)
class GroupChange:
    """Что изменилось после правки групп."""

    moved: int = 0
    groups: int = 0


async def move_to_group(
    session: AsyncSession,
    keyword_ids: Sequence[uuid.UUID],
    *,
    project_id: uuid.UUID,
    group: str | None,
) -> GroupChange:
    """Переносит выбранные фразы в группу.

    `group=None` означает «убрать из групп»: фраза остаётся в ядре, но в
    структуру кампании не идёт. Удалять её ради этого нельзя — она собрана,
    у неё есть частотность, и завтра для неё найдётся место.

    Перенесённые фразы помечаются ручными: со следующего пересчёта расчёт их
    не трогает. Иначе перенос жил бы до ближайшего сбора.
    """
    name = (group or "").strip()[:MAX_GROUP_NAME] or None

    rows = list(
        (
            await session.execute(
                select(Keyword)
                .where(Keyword.project_id == project_id)
                .where(Keyword.id.in_(list(keyword_ids)))
            )
        )
        .scalars()
        .all()
    )

    for row in rows:
        row.cluster_name = name
        row.cluster_manual = True

    await session.flush()
    return GroupChange(moved=len(rows), groups=await count_groups(session, project_id=project_id))


async def rename_group(
    session: AsyncSession, *, project_id: uuid.UUID, old: str, new: str
) -> GroupChange:
    """Переименовывает группу.

    Все её фразы становятся ручными. Иначе имя жило бы до первого пересчёта:
    расчёт заново вывел бы своё название из общих основ слов и стёр то,
    которое дал человек.
    """
    name = new.strip()[:MAX_GROUP_NAME]
    if not name:
        raise ValueError("Название группы не может быть пустым")

    rows = list(
        (
            await session.execute(
                select(Keyword)
                .where(Keyword.project_id == project_id)
                .where(Keyword.cluster_name == old)
            )
        )
        .scalars()
        .all()
    )

    for row in rows:
        row.cluster_name = name
        row.cluster_manual = True

    await session.flush()
    return GroupChange(moved=len(rows), groups=await count_groups(session, project_id=project_id))


async def dissolve_group(
    session: AsyncSession, *, project_id: uuid.UUID, name: str
) -> GroupChange:
    """Распускает группу: фразы остаются, группы больше нет.

    Фразы при этом не помечаются ручными — наоборот, возвращаются расчёту.
    Человек сказал «эта группа неверна», а не «этих фраз не должно быть в
    структуре»; следующий пересчёт разложит их заново.
    """
    rows = list(
        (
            await session.execute(
                select(Keyword)
                .where(Keyword.project_id == project_id)
                .where(Keyword.cluster_name == name)
            )
        )
        .scalars()
        .all()
    )

    for row in rows:
        row.cluster_name = None
        row.cluster_manual = False

    await session.flush()
    return GroupChange(moved=len(rows), groups=await count_groups(session, project_id=project_id))


async def count_groups(session: AsyncSession, *, project_id: uuid.UUID) -> int:
    rows = (
        await session.execute(
            select(Keyword.cluster_name)
            .where(Keyword.project_id == project_id)
            .where(Keyword.cluster_name.is_not(None))
            .distinct()
        )
    ).scalars()
    return len(list(rows))
