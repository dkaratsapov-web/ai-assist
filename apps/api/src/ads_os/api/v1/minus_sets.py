"""Наборы минус-слов: сохранение, применение, удаление."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status
from sqlalchemy import Select, select

from ...db.base import utcnow
from ...errors import AppError
from ...models import Keyword, MinusWord, MinusWordSet, Project
from ...models.activity import ActivityAction
from ...services.activity import record
from ...services.semantics import classify
from ...tenancy.repository import TenantRepository
from ..deps import SessionDep, TenantDep, WriteDep
from ..schemas import (
    ApplySetResult,
    MinusWordSetCreate,
    MinusWordSetList,
    MinusWordSetRead,
)

router = APIRouter(tags=["minus-sets"])

#: Предел на набор. Не защита от злого умысла: список из тысячи слов невозможно
#: проверить глазами, а непроверенный минус-список молча отсекает нужное.
MAX_WORDS_PER_SET = 500


class ProjectRepository(TenantRepository[Project]):
    model = Project


class SetRepository(TenantRepository[MinusWordSet]):
    model = MinusWordSet

    def scoped(self, *, include_deleted: bool = False) -> Select[tuple[MinusWordSet]]:
        return select(self.model).where(self.model.organization_id == self.ctx.organization_id)


class MinusWordRepository(TenantRepository[MinusWord]):
    model = MinusWord

    def scoped(self, *, include_deleted: bool = False) -> Select[tuple[MinusWord]]:
        return select(self.model).where(self.model.organization_id == self.ctx.organization_id)


class SetNotFoundError(AppError):
    status_code = 404
    error_code = "minus_word_set_not_found"
    message = "Набор не найден"


class EmptySetError(AppError):
    status_code = 422
    error_code = "empty_set"
    message = "Набор пуст: в проекте нет минус-слов и слова не переданы"


class DuplicateSetError(AppError):
    status_code = 409
    error_code = "duplicate_set"
    message = "Набор с таким названием уже есть"


class TooManyWordsError(AppError):
    status_code = 422
    error_code = "too_many_words"
    message = f"В наборе не больше {MAX_WORDS_PER_SET} слов"


@router.get("/minus-word-sets", response_model=MinusWordSetList, summary="Наборы минус-слов")
async def list_sets(session: SessionDep, ctx: TenantDep) -> MinusWordSetList:
    rows = sorted(
        (await session.execute(SetRepository(session, ctx).scoped())).scalars().all(),
        key=lambda row: row.name,
    )

    return MinusWordSetList(items=[_to_read(row) for row in rows], total=len(rows))


@router.post(
    "/minus-word-sets",
    response_model=MinusWordSetRead,
    status_code=status.HTTP_201_CREATED,
    summary="Сохранить набор",
)
async def create_set(
    payload: MinusWordSetCreate, session: SessionDep, ctx: WriteDep
) -> MinusWordSetRead:
    """Сохраняет набор — свой список либо минус-слова готового проекта.

    Второй способ и есть основной: набор обычно рождается не из желания завести
    набор, а из работы. Сначала минус-слова собираются в проекте, а потом
    выясняется, что они пригодятся и в следующем.
    """
    words = _clean(payload.words)

    if not words and payload.source_project_id is not None:
        await ProjectRepository(session, ctx).get_or_404(payload.source_project_id)
        rows = (
            (
                await session.execute(
                    MinusWordRepository(session, ctx)
                    .scoped()
                    .where(MinusWord.project_id == payload.source_project_id)
                )
            )
            .scalars()
            .all()
        )
        words = _clean([row.word for row in rows])

    if not words:
        raise EmptySetError()
    if len(words) > MAX_WORDS_PER_SET:
        raise TooManyWordsError()

    existing = (
        await session.execute(
            SetRepository(session, ctx).scoped().where(MinusWordSet.name == payload.name)
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise DuplicateSetError()

    row = MinusWordSet(name=payload.name, words=words, created_by_id=ctx.user_id)
    await SetRepository(session, ctx).add(row)
    await session.flush()

    await record(
        session,
        ctx,
        ActivityAction.MINUS_SET_SAVED,
        subject=payload.name,
        actor_name=ctx.user_name,
        details={"слов": str(len(words))},
    )

    return _to_read(row)


@router.post(
    "/projects/{project_id}/minus-words/apply/{set_id}",
    response_model=ApplySetResult,
    summary="Применить набор к проекту",
)
async def apply_set(
    project_id: uuid.UUID, set_id: uuid.UUID, session: SessionDep, ctx: WriteDep
) -> ApplySetResult:
    """Добавляет слова набора к минус-словам проекта и перепроверяет ядро.

    Слова добавляются, а не заменяют существующие: набор — это заготовка, а не
    источник правды о проекте. Заменяя, система стёрла бы то, что специалист
    нашёл именно здесь, — и восстановить это было бы неоткуда.
    """
    project = await ProjectRepository(session, ctx).get_or_404(project_id)

    row = (
        await session.execute(
            SetRepository(session, ctx).scoped().where(MinusWordSet.id == set_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise SetNotFoundError()

    current = (
        (
            await session.execute(
                MinusWordRepository(session, ctx)
                .scoped()
                .where(MinusWord.project_id == project_id)
            )
        )
        .scalars()
        .all()
    )
    present = {item.word for item in current}

    added = 0
    for word in row.words:
        if word in present:
            continue
        await MinusWordRepository(session, ctx).add(MinusWord(project_id=project_id, word=word))
        present.add(word)
        added += 1

    await session.flush()

    # Ядро перепроверяется целиком: набор, не изменивший ни одной фразы,
    # выглядит как применённый, хотя не сделал ничего. Ручные решения при этом
    # не трогаются.
    keywords = (
        (
            await session.execute(
                select(Keyword)
                .where(Keyword.organization_id == ctx.organization_id)
                .where(Keyword.project_id == project_id)
            )
        )
        .scalars()
        .all()
    )
    for keyword in keywords:
        if keyword.is_manual:
            continue
        result = classify(keyword.phrase, extra_irrelevant=frozenset(present))
        keyword.intent = result.intent
        keyword.trigger = result.trigger

    await session.flush()

    await record(
        session,
        ctx,
        ActivityAction.MINUS_SET_APPLIED,
        subject=project.name,
        actor_name=ctx.user_name,
        project_id=project_id,
        details={"набор": row.name, "добавлено": str(added)},
    )

    return ApplySetResult(added=added, already_present=len(row.words) - added)


@router.delete(
    "/minus-word-sets/{set_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить набор",
)
async def delete_set(set_id: uuid.UUID, session: SessionDep, ctx: WriteDep) -> None:
    """Удаляет набор.

    Уже применённые слова остаются в проектах: они стали частью работы над
    ними, и снимать их вслед за удалением заготовки означало бы менять проекты,
    которых человек в этот момент даже не открывал.
    """
    row = (
        await session.execute(
            SetRepository(session, ctx).scoped().where(MinusWordSet.id == set_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise SetNotFoundError()

    await session.delete(row)
    await session.flush()


def _clean(words: list[str]) -> list[str]:
    """Приводит слова к единому виду и убирает повторы, сохраняя порядок."""
    seen: set[str] = set()
    cleaned: list[str] = []

    for raw in words:
        word = raw.strip().lower().lstrip("-")
        if not word or len(word) > 60 or word in seen:
            continue
        seen.add(word)
        cleaned.append(word)

    return cleaned


def _to_read(row: MinusWordSet) -> MinusWordSetRead:
    return MinusWordSetRead(
        id=row.id,
        name=row.name,
        words=list(row.words or []),
        created_at=row.created_at or utcnow(),
    )
