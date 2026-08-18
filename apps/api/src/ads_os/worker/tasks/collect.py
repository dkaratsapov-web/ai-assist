"""Сбор частотностей по маскам.

Задание берёт маски, построенные из брифа, проходит по ним в Вордстате и
складывает найденные фразы в ядро проекта.

Всё устройство этого модуля продиктовано одним числом: **сто запросов в час на
весь сервис**. Отсюда три решения, которые иначе выглядели бы странно.

**Собранное сохраняется после каждой маски, а не в конце.** Сбор может
прерваться на середине — кончилась квота, площадка не ответила, воркер
перезапустили. Всё, что уже добыто, к этому моменту оплачено запросами, и
терять его нельзя: повтор стоил бы той же квоты.

**Кончившаяся квота — не ошибка, а пауза.** Задание отмечает, когда лимит
обновится, и само возвращается к работе. Показывать человеку «сбор не удался»
там, где надо просто подождать сорок минут, значит заставить его нажать
«повторить» и потратить ещё запросов впустую.

**Маски идут по одной, с паузой.** Скорость здесь ничего не решает: сбор всё
равно фоновый. Ровный ритм зато не даёт упереться во второй, посекундный
предел площадки.

Ручной путь никуда не девается. У Key Collector своя глубина, а квота здесь
кончается — и в этот момент нужно чем-то работать.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import select

from ...db.base import utcnow
from ...db.session import session_scope
from ...models.audit import ModuleStatus
from ...models.collection import KeywordCollection
from ...models.project import Project
from ...models.semantics import KeywordBrief
from ...models.usage import UsageService, UsageUnit
from ...services import keyword_store, niches, wordstat, wordstat_api, wordstat_quota
from ...services.usage import record as record_usage
from ..app import celery_app
from ..runtime import run_task

logger = logging.getLogger(__name__)

#: Сколько фраз просим по каждой маске. Не предел площадки: две тысячи фраз на
#: маску — это список, который человек не прочитает, а чистить его придётся
#: всё равно. Пятьсот дают ядро с хвостом и оставляют разбор обозримым.
PHRASES_PER_MASK = 500

#: Состояния маски внутри сбора.
PENDING = "pending"
DONE = "done"
FAILED = "failed"


@celery_app.task(name="ads_os.worker.tasks.collect.collect_frequencies")
def collect_frequencies(collection_id: str) -> str:
    """Собирает частотности. Возвращается к себе, когда упирается в квоту."""
    return run_task(lambda: _collect(uuid.UUID(collection_id)))


async def _collect(collection_id: uuid.UUID) -> str:
    async with session_scope() as session:
        collection = (
            await session.execute(
                select(KeywordCollection).where(KeywordCollection.id == collection_id)
            )
        ).scalar_one_or_none()

        if collection is None:
            logger.warning("сбор не найден", extra={"collection_id": str(collection_id)})
            return "not_found"

        if collection.is_finished:
            # Очередь может доставить задачу повторно — это норма, и переделывать
            # работу не нужно (v0.3 §33).
            return collection.status.value

        project = (
            await session.execute(select(Project).where(Project.id == collection.project_id))
        ).scalar_one_or_none()

        if project is None:
            return await _fail(collection, "Проект удалён.")

        source = wordstat_api.get_source()
        if isinstance(source, wordstat_api.NullSource):
            return await _fail(
                collection,
                "Сбор частотностей не подключён: не задан ключ доступа к Вордстату.",
            )

        collection.status = ModuleStatus.RUNNING
        collection.started_at = collection.started_at or utcnow()
        collection.resumes_at = None
        await session.flush()

        quota = wordstat_quota.get_quota()
        extra = await keyword_store.minus_words(session, project_id=project.id)
        masks = list(collection.masks or [])

        for index, mask in enumerate(masks):
            if mask.get("state") != PENDING:
                continue

            if not await quota.take():
                # Не ошибка, а пауза: лимит обновится в начале следующего часа.
                return await _pause(session, collection, masks)

            outcome = await _one(
                source,
                session,
                mask,
                project=project,
                collection=collection,
                extra_irrelevant=extra,
            )

            masks[index] = outcome.mask
            collection.requests += 1
            collection.added += outcome.added
            collection.updated += outcome.updated
            # Новый список, а не правка на месте: изменение внутри JSONB
            # SQLAlchemy сама не замечает, и сохранённым оказалось бы прежнее
            # состояние — то есть после перерыва сбор пошёл бы по второму кругу.
            collection.masks = list(masks)
            await session.flush()

            if outcome.pause:
                return await _pause(session, collection, masks)

            await asyncio.sleep(wordstat_quota.PAUSE_SECONDS)

        groups = await keyword_store.recluster(session, project_id=project.id)

        await record_usage(
            session,
            organization_id=collection.organization_id,
            service=UsageService.EXTERNAL_API,
            operation="wordstat_collect",
            quantity=collection.requests,
            unit=UsageUnit.REQUESTS,
            project_id=project.id,
            meta={"масок": str(len(masks))},
        )

        collection.status = ModuleStatus.COMPLETED
        collection.finished_at = utcnow()

        logger.info(
            "сбор частотностей завершён",
            extra={
                "collection_id": str(collection_id),
                "added": collection.added,
                "updated": collection.updated,
                "groups": groups,
            },
        )
        return ModuleStatus.COMPLETED.value


class _Outcome:
    """Что стало с одной маской."""

    __slots__ = ("added", "mask", "pause", "updated")

    def __init__(
        self, mask: dict[str, Any], *, added: int = 0, updated: int = 0, pause: bool = False
    ) -> None:
        self.mask = mask
        self.added = added
        self.updated = updated
        #: Останавливаться ли после этой маски. Так помечается отказ, который
        #: имеет смысл повторить позже.
        self.pause = pause


async def _one(
    source: wordstat_api.WordstatSource,
    session: Any,
    mask: dict[str, Any],
    *,
    project: Project,
    collection: KeywordCollection,
    extra_irrelevant: frozenset[str],
) -> _Outcome:
    """Обрабатывает одну маску."""
    query = str(mask.get("query") or "")

    try:
        result = await source.top(query, num_phrases=PHRASES_PER_MASK)
    except wordstat_api.WordstatError as error:
        if error.retryable:
            # Квота площадки или её сбой. Маска остаётся невыполненной и будет
            # взята при следующем заходе — переделывать уже собранное не надо.
            return _Outcome({**mask, "reason": error.reason}, pause=True)

        logger.info("маска не собралась", extra={"reason": error.reason})
        return _Outcome({**mask, "state": FAILED, "reason": error.reason})

    stored = await keyword_store.upsert(
        session,
        [keyword_store.Phrase(item.phrase, item.count) for item in result.results],
        organization_id=collection.organization_id,
        project_id=project.id,
        region=project.primary_region,
        extra_irrelevant=extra_irrelevant,
    )

    return _Outcome(
        {
            **mask,
            "state": DONE,
            "found": len(result.results),
            "total": result.total,
            "reason": "",
        },
        added=stored.added,
        updated=stored.updated,
    )


async def _pause(session: Any, collection: KeywordCollection, masks: list[dict[str, Any]]) -> str:
    """Останавливает сбор до обновления лимита и записывается на продолжение."""
    wait = wordstat_quota.seconds_until_reset()

    collection.masks = list(masks)
    collection.status = ModuleStatus.RUNNING
    collection.resumes_at = utcnow() + timedelta(seconds=wait)
    await session.flush()

    collect_frequencies.apply_async(args=[str(collection.id)], countdown=wait + 5)

    logger.info(
        "сбор приостановлен до обновления квоты",
        extra={"collection_id": str(collection.id), "wait_seconds": wait},
    )
    return "paused"


async def _fail(collection: KeywordCollection, reason: str) -> str:
    collection.status = ModuleStatus.FAILED
    collection.error_reason = reason
    collection.finished_at = utcnow()
    return ModuleStatus.FAILED.value


def build_masks(project: Project, brief: KeywordBrief | None) -> list[dict[str, Any]]:
    """Маски для сбора — те же, что человек видит на экране.

    Именно те же: если бы сборщик строил свои, человек собирал бы руками одно,
    а система — другое, и расхождение обнаружилось бы уже в готовом ядре.
    """
    source = wordstat.Brief(
        sells=(brief.sells if brief else "") or "",
        synonyms=(brief.synonyms if brief else "") or "",
        excludes=(brief.excludes if brief else "") or "",
        cities=(brief.cities if brief else "") or "",
    )

    niche = niches.get(project.niche)
    built = wordstat.masks(
        source,
        niche_words=niches.minus_words(niche),
        region=project.primary_region,
    )

    return [
        {"query": item.query, "purpose": item.purpose, "state": PENDING, "reason": ""}
        for item in built
    ]


def enqueue_collection(collection_id: uuid.UUID) -> None:
    collect_frequencies.delay(str(collection_id))
