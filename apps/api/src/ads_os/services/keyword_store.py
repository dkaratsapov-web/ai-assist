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
from collections.abc import Iterable
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
    """
    rows = list(
        (await session.execute(select(Keyword).where(Keyword.project_id == project_id)))
        .scalars()
        .all()
    )

    # Нецелевые в группы не идут: группа собирается под объявление, а по
    # нецелевым фразам объявлений не делают.
    groups = cluster(
        [
            ParsedKeyword(row.phrase, row.frequency)
            for row in rows
            if row.intent is not Intent.IRRELEVANT
        ]
    )

    by_phrase = {phrase: group.name for group in groups for phrase in group.phrases}
    for row in rows:
        row.cluster_name = by_phrase.get(row.phrase)

    await session.flush()
    return len(groups)
