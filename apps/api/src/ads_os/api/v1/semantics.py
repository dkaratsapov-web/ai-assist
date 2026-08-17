"""Семантика: импорт списка, разбор, группы, минус-слова."""

from __future__ import annotations

import uuid
from collections import defaultdict
from urllib.parse import quote

from fastapi import APIRouter, Query, Response, status
from sqlalchemy import Select, select

from ...errors import AppError
from ...models import Keyword, MinusWord, Project, SiteAudit
from ...models.activity import ActivityAction
from ...models.audit import ModuleStatus
from ...services import niches
from ...services.activity import record
from ...services.ads import build_variants
from ...services.cross_minus import cross_minus
from ...services.export import ExportRow, file_name, to_csv
from ...services.semantics import (
    INTENT_LABELS,
    Intent,
    LandingPage,
    ParsedKeyword,
    classify,
    cluster,
    match_landing,
    parse_list,
    suggest_minus_words,
)
from ...tenancy.repository import TenantRepository
from ..deps import SessionDep, TenantDep, WriteDep
from ..schemas import (
    AdDraftList,
    AdDraftRead,
    AdViolationRead,
    ClusterList,
    ClusterRead,
    CrossMinusRead,
    CrossMinusResultRead,
    DuplicateRead,
    ImportSummary,
    KeywordImport,
    KeywordList,
    KeywordRead,
    KeywordUpdate,
    MinusWordCreate,
    MinusWordList,
    MinusWordRead,
    MinusWordSuggestionRead,
    SearchKeywordRead,
    SearchProjectRead,
    SearchResult,
    SitelinkRead,
)

router = APIRouter(prefix="/projects", tags=["semantics"])

#: Поиск живёт на отдельном маршруте, а не под префиксом проектов.
#:
#: Под префиксом он стал бы «/projects/search» и попал бы под «/projects/{id}»:
#: слово «search» не является идентификатором, и запрос отвечал бы ошибкой
#: разбора. Эти грабли в проекте уже случались с «/projects/overview».
search_router = APIRouter(tags=["search"])

#: Предел на один импорт. Не защита от злого умысла, а защита от случайности:
#: вставленный целиком файл на миллион строк обработается, но экран после этого
#: будет непригоден для работы, а пользователь решит, что всё сломалось.
MAX_KEYWORDS_PER_IMPORT = 20_000


class ProjectRepository(TenantRepository[Project]):
    model = Project


class KeywordRepository(TenantRepository[Keyword]):
    model = Keyword

    def scoped(self, *, include_deleted: bool = False) -> Select[tuple[Keyword]]:
        return select(self.model).where(self.model.organization_id == self.ctx.organization_id)


class MinusWordRepository(TenantRepository[MinusWord]):
    model = MinusWord

    def scoped(self, *, include_deleted: bool = False) -> Select[tuple[MinusWord]]:
        return select(self.model).where(self.model.organization_id == self.ctx.organization_id)


class TooManyKeywordsError(AppError):
    status_code = 422
    error_code = "too_many_keywords"
    message = f"За один раз принимается не больше {MAX_KEYWORDS_PER_IMPORT} фраз"


class KeywordNotFoundError(AppError):
    status_code = 404
    error_code = "keyword_not_found"
    message = "Фраза не найдена"


@router.post(
    "/{project_id}/keywords/import",
    response_model=ImportSummary,
    summary="Загрузить список фраз",
)
async def import_keywords(
    project_id: uuid.UUID, payload: KeywordImport, session: SessionDep, ctx: WriteDep
) -> ImportSummary:
    """Разбирает вставленный список и сохраняет фразы.

    Повторный импорт того же списка не удваивает ядро: фраза в проекте
    существует один раз, повторная загрузка обновляет её частотность. Ручные
    решения при этом сохраняются — если специалист отнёс фразу к нецелевым,
    словарь её больше не трогает. Иначе правка терялась бы при каждой загрузке,
    и доверие к ручным решениям исчезло бы вместе с ней.
    """
    project = await ProjectRepository(session, ctx).get_or_404(project_id)

    parsed = parse_list(payload.text)
    if len(parsed) > MAX_KEYWORDS_PER_IMPORT:
        raise TooManyKeywordsError()

    lines = sum(1 for line in payload.text.splitlines() if line.strip())
    skipped = max(0, lines - len(parsed))

    existing = {row.phrase: row for row in await _keywords(session, ctx, project_id)}
    extra = await _minus_words_set(session, ctx, project_id)

    added = updated = 0

    for item in parsed:
        row = existing.get(item.phrase)

        if row is None:
            result = classify(item.phrase, extra_irrelevant=extra)
            row = Keyword(
                project_id=project_id,
                phrase=item.phrase,
                frequency=item.frequency,
                intent=result.intent,
                trigger=result.trigger,
            )
            await KeywordRepository(session, ctx).add(row)
            existing[item.phrase] = row
            added += 1
        else:
            if item.frequency is not None:
                row.frequency = item.frequency
            if not row.is_manual:
                result = classify(item.phrase, extra_irrelevant=extra)
                row.intent = result.intent
                row.trigger = result.trigger
            updated += 1

    await session.flush()

    rows = list(existing.values())
    clusters = _recluster(rows)

    await record(
        session,
        ctx,
        ActivityAction.KEYWORDS_IMPORTED,
        subject=project.name,
        actor_name=ctx.user_name,
        project_id=project_id,
        details={"добавлено": str(added), "обновлено": str(updated)},
    )

    return ImportSummary(
        added=added,
        updated=updated,
        skipped=skipped,
        commercial=sum(1 for r in rows if r.intent is Intent.COMMERCIAL),
        informational=sum(1 for r in rows if r.intent is Intent.INFORMATIONAL),
        irrelevant=sum(1 for r in rows if r.intent is Intent.IRRELEVANT),
        clusters=clusters,
    )


@router.get("/{project_id}/keywords", response_model=KeywordList, summary="Фразы проекта")
async def list_keywords(
    project_id: uuid.UUID,
    session: SessionDep,
    ctx: TenantDep,
    intent: Intent | None = None,
    cluster_name: str | None = None,
    limit: int = Query(default=200, ge=1, le=2000),
) -> KeywordList:
    await ProjectRepository(session, ctx).get_or_404(project_id)

    rows = await _keywords(session, ctx, project_id)

    if intent is not None:
        rows = [row for row in rows if row.intent is intent]
    if cluster_name is not None:
        rows = [row for row in rows if row.cluster_name == cluster_name]

    # Сначала частотные: с них начинают работу, и они определяют, окупится ли
    # кампания. Фразы без известной частотности идут после — не потому что они
    # хуже, а потому что о них ничего не известно.
    rows.sort(key=lambda row: (-(row.frequency or 0), row.phrase))

    return KeywordList(items=[_to_read(row) for row in rows[:limit]], total=len(rows))


@router.patch(
    "/{project_id}/keywords/{keyword_id}",
    response_model=KeywordRead,
    summary="Изменить тип фразы",
)
async def update_keyword(
    project_id: uuid.UUID,
    keyword_id: uuid.UUID,
    payload: KeywordUpdate,
    session: SessionDep,
    ctx: WriteDep,
) -> KeywordRead:
    """Переносит фразу в другой тип.

    Решение помечается ручным и переживает повторные импорты. Словарь не знает
    ни ниши, ни клиента и ошибается в обе стороны — последнее слово всегда за
    специалистом.
    """
    await ProjectRepository(session, ctx).get_or_404(project_id)

    row = next(
        (r for r in await _keywords(session, ctx, project_id) if r.id == keyword_id), None
    )
    if row is None:
        raise KeywordNotFoundError()

    row.intent = payload.intent
    row.is_manual = True
    row.trigger = None
    await session.flush()

    return _to_read(row)


@router.get(
    "/{project_id}/keywords/clusters",
    response_model=ClusterList,
    summary="Группы фраз под объявления",
)
async def list_clusters(
    project_id: uuid.UUID, session: SessionDep, ctx: TenantDep
) -> ClusterList:
    """Группы считаются заново при каждом запросе.

    Хранить их отдельно смысла нет: они целиком выводятся из фраз, а фразы
    меняются. Сохранённая группа разошлась бы с ядром при первой же правке
    типа, и человек увидел бы структуру, которой уже нет.
    """
    await ProjectRepository(session, ctx).get_or_404(project_id)

    rows = await _keywords(session, ctx, project_id)
    groups = cluster(_targeted(rows))

    return ClusterList(
        items=[
            ClusterRead(
                name=group.name,
                core=list(group.core),
                phrases=len(group.phrases),
                total_frequency=group.total_frequency,
            )
            for group in groups
        ],
        total=len(groups),
    )


#: Со скольких проектов слово считается вашим решением, а не случайностью.
#: Два — это уже повторение; на одном проекте нельзя отличить нишевое слово от
#: разовой правки.
REPEATED_DECISION_PROJECTS = 2


@router.get(
    "/{project_id}/minus-words",
    response_model=MinusWordList,
    summary="Минус-слова и предложения",
)
async def list_minus_words(
    project_id: uuid.UUID, session: SessionDep, ctx: TenantDep
) -> MinusWordList:
    project = await ProjectRepository(session, ctx).get_or_404(project_id)

    rows = await _minus_word_rows(session, ctx, project_id)
    saved = {row.word for row in rows}

    keywords = await _keywords(session, ctx, project_id)
    suggestions = [
        MinusWordSuggestionRead(
            word=item.word, phrases=item.phrases, examples=list(item.examples)
        )
        for item in suggest_minus_words(
            [ParsedKeyword(row.phrase, row.frequency) for row in keywords],
            extra_irrelevant=frozenset(saved),
        )
        # Уже добавленное не предлагается повторно: список предложений должен
        # быть списком дел, а не отчётом о проделанной работе.
        if item.word not in saved
    ]

    return MinusWordList(
        items=[MinusWordRead(id=row.id, word=row.word) for row in rows],
        suggestions=suggestions,
        learned=await _learned_words(session, ctx, project_id, already=saved),
        from_niche=[
            word
            for word in niches.minus_words(niches.get(project.niche))
            if word not in saved
        ],
        total=len(rows),
    )


async def _learned_words(
    session: SessionDep,
    ctx: TenantDep,
    project_id: uuid.UUID,
    *,
    already: set[str],
) -> list[str]:
    """Слова, которые вы сами относили к нецелевым в других проектах.

    Словарь не знает ни ниши, ни клиента. Зато знает специалист — и, отнеся
    «рассрочка» к нецелевым в двух проектах, он уже принял решение, которое
    системе остаётся заметить, а не заставлять повторять в третий раз.

    Подсказка именно подсказка: слово не добавляется само. Тихое применение
    чужого решения к новому проекту — это отсечённый трафик, о котором человек
    не просил и о котором не узнает.
    """
    rows = (
        (
            await session.execute(
                select(MinusWord.word, MinusWord.project_id)
                .where(MinusWord.organization_id == ctx.organization_id)
                .where(MinusWord.project_id != project_id)
            )
        )
        .tuples()
        .all()
    )

    by_word: dict[str, set[uuid.UUID]] = defaultdict(set)
    for word, other_project in rows:
        by_word[word].add(other_project)

    return sorted(
        word
        for word, projects in by_word.items()
        if len(projects) >= REPEATED_DECISION_PROJECTS and word not in already
    )


@router.post(
    "/{project_id}/minus-words",
    response_model=MinusWordRead,
    status_code=status.HTTP_201_CREATED,
    summary="Добавить минус-слово",
)
async def add_minus_word(
    project_id: uuid.UUID, payload: MinusWordCreate, session: SessionDep, ctx: WriteDep
) -> MinusWordRead:
    """Добавляет слово и перепроверяет по нему всё ядро.

    Перепроверка обязательна: минус-слово, не изменившее ни одной фразы,
    выглядит как принятое решение, хотя не сделало ничего. Ручные решения при
    этом не трогаются.
    """
    project = await ProjectRepository(session, ctx).get_or_404(project_id)

    word = payload.word.strip().lower()
    rows = await _minus_word_rows(session, ctx, project_id)

    existing = next((row for row in rows if row.word == word), None)
    if existing is not None:
        return MinusWordRead(id=existing.id, word=existing.word)

    row = MinusWord(project_id=project_id, word=word)
    await MinusWordRepository(session, ctx).add(row)
    await session.flush()

    extra = {r.word for r in rows} | {word}
    for keyword in await _keywords(session, ctx, project_id):
        if keyword.is_manual:
            continue
        result = classify(keyword.phrase, extra_irrelevant=frozenset(extra))
        keyword.intent = result.intent
        keyword.trigger = result.trigger

    await session.flush()

    await record(
        session,
        ctx,
        ActivityAction.MINUS_WORD_ADDED,
        subject=project.name,
        actor_name=ctx.user_name,
        project_id=project_id,
        details={"слово": word},
    )

    return MinusWordRead(id=row.id, word=row.word)


@router.delete(
    "/{project_id}/minus-words/{minus_word_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Убрать минус-слово",
)
async def delete_minus_word(
    project_id: uuid.UUID, minus_word_id: uuid.UUID, session: SessionDep, ctx: WriteDep
) -> None:
    await ProjectRepository(session, ctx).get_or_404(project_id)

    rows = await _minus_word_rows(session, ctx, project_id)
    row = next((r for r in rows if r.id == minus_word_id), None)
    if row is None:
        raise KeywordNotFoundError()

    await session.delete(row)
    await session.flush()

    remaining = frozenset(r.word for r in rows if r.id != minus_word_id)
    for keyword in await _keywords(session, ctx, project_id):
        if keyword.is_manual:
            continue
        result = classify(keyword.phrase, extra_irrelevant=remaining)
        keyword.intent = result.intent
        keyword.trigger = result.trigger

    await session.flush()


def _targeted(rows: list[Keyword]) -> list[ParsedKeyword]:
    """Фразы, которые пойдут в кампанию.

    Нецелевые в группировке не участвуют: они и существуют для того, чтобы по
    ним не показываться, а попав в группу, они утянули бы за собой название и
    объявление.
    """
    return [
        ParsedKeyword(row.phrase, row.frequency)
        for row in rows
        if row.intent is not Intent.IRRELEVANT
    ]


def _recluster(rows: list[Keyword]) -> int:
    """Проставляет фразам название группы. Возвращает число групп."""
    groups = cluster(_targeted(rows))

    by_phrase = {phrase: group.name for group in groups for phrase in group.phrases}
    for row in rows:
        row.cluster_name = by_phrase.get(row.phrase)

    return len(groups)


async def _keywords(
    session: SessionDep, ctx: TenantDep, project_id: uuid.UUID
) -> list[Keyword]:
    stmt = KeywordRepository(session, ctx).scoped().where(Keyword.project_id == project_id)
    return list((await session.execute(stmt)).scalars().all())


async def _minus_word_rows(
    session: SessionDep, ctx: TenantDep, project_id: uuid.UUID
) -> list[MinusWord]:
    stmt = (
        MinusWordRepository(session, ctx).scoped().where(MinusWord.project_id == project_id)
    )
    return sorted((await session.execute(stmt)).scalars().all(), key=lambda row: row.word)


async def _minus_words_set(
    session: SessionDep, ctx: TenantDep, project_id: uuid.UUID
) -> frozenset[str]:
    return frozenset(row.word for row in await _minus_word_rows(session, ctx, project_id))


def _to_read(row: Keyword) -> KeywordRead:
    return KeywordRead(
        id=row.id,
        phrase=row.phrase,
        frequency=row.frequency,
        intent=row.intent,
        intent_label=INTENT_LABELS[row.intent],
        trigger=row.trigger,
        is_manual=row.is_manual,
        cluster_name=row.cluster_name,
    )


@router.get(
    "/{project_id}/ads",
    response_model=AdDraftList,
    summary="Черновики объявлений по группам фраз",
)
async def list_ad_drafts(
    project_id: uuid.UUID, session: SessionDep, ctx: TenantDep
) -> AdDraftList:
    """Собирает по черновику на каждую группу фраз.

    Текст берётся с посадочной страницы клиента — из последнего завершённого
    аудита. Сочинять его система не будет: объявление, обещающее то, чего на
    сайте нет, — это отказ на модерации в лучшем случае и претензия клиента в
    худшем.

    Ничего не сохраняется. Черновик выводится из фраз и содержимого страницы;
    и то и другое меняется, а сохранённый черновик молча устарел бы и разошёлся
    с тем, что человек видит на других экранах.
    """
    project = await ProjectRepository(session, ctx).get_or_404(project_id)

    rows = await _keywords(session, ctx, project_id)
    groups = cluster(_targeted(rows))

    audit = (
        await session.execute(
            select(SiteAudit)
            .where(SiteAudit.organization_id == ctx.organization_id)
            .where(SiteAudit.project_id == project_id)
            .where(SiteAudit.status == ModuleStatus.COMPLETED)
            .order_by(SiteAudit.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    points: tuple[str, ...] = ()
    links: tuple[tuple[str, str], ...] = ()
    note: str | None = None

    if audit is None:
        note = (
            "Сайт ещё не проверяли, поэтому тексты пустые: брать их неоткуда. "
            "Запустите аудит — черновики соберутся из предложения на странице."
        )
    else:
        points = tuple(audit.selling_points or [])
        links = tuple(
            (str(pair[0]), str(pair[1]))
            for pair in (audit.internal_links or [])
            if isinstance(pair, list) and len(pair) == 2
        )
        if not points:
            note = (
                "На проверенной странице не нашлось ни цены, ни срока, ни гарантии — "
                "собирать текст не из чего. Тексты придётся написать вручную."
            )

    pages = await _landing_pages(session, ctx, project_id)
    fallback = project.website_url or ""

    drafts = [
        (group, variant)
        for group in groups
        for variant in build_variants(
            cluster_name=group.name,
            keywords=group.phrases,
            selling_points=points,
            region=project.primary_region,
            internal_links=links,
        )
        # Остаток — это не группа под объявление, а фразы, которым не нашлось
        # места. Собирать по ним объявление значило бы делать вид, что оно есть.
        if group.core
    ]

    return AdDraftList(
        items=[
            AdDraftRead(
                cluster=draft.cluster,
                landing_url=match_landing(group.core, pages, fallback=fallback),
                title=draft.title,
                title_2=draft.title_2,
                text=draft.text,
                display_path=draft.display_path,
                callouts=list(draft.callouts),
                sitelinks=[
                    SitelinkRead(title=link.title, url=link.url) for link in draft.sitelinks
                ],
                keywords=list(draft.keywords),
                violations=[
                    AdViolationRead(
                        problem=v.problem, field_name=v.field_name, message=v.message
                    )
                    for v in draft.violations
                ],
                is_ready=draft.is_ready,
            )
            for group, draft in drafts
        ],
        total=len(drafts),
        ready=sum(1 for _, draft in drafts if draft.is_ready),
        source_note=note,
    )


@router.get(
    "/{project_id}/cross-minus",
    response_model=CrossMinusResultRead,
    summary="Пересечения фраз и кросс-минусовка",
)
async def get_cross_minus(
    project_id: uuid.UUID, session: SessionDep, ctx: TenantDep
) -> CrossMinusResultRead:
    """Считает, какие фразы перехватывают запросы соседних.

    Считается по всему ядру, а не внутри групп: перехват через границу группы
    заметить труднее всего, а вредит он ровно так же.
    """
    await ProjectRepository(session, ctx).get_or_404(project_id)

    keywords = await _keywords(session, ctx, project_id)
    result = cross_minus([k.phrase for k in _targeted(keywords)])

    return CrossMinusResultRead(
        items=[
            CrossMinusRead(
                phrase=item.phrase,
                minus_words=list(item.minus_words),
                shadows=list(item.shadows),
            )
            for item in result.items
        ],
        duplicates=[DuplicateRead(phrases=list(d.phrases)) for d in result.duplicates],
        analyzed=result.analyzed,
    )


@router.get(
    "/{project_id}/campaign/export.csv",
    summary="Выгрузка кампании файлом",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}, "description": "CSV с кампанией"}},
)
async def export_campaign(
    project_id: uuid.UUID, session: SessionDep, ctx: TenantDep
) -> Response:
    """Отдаёт готовую кампанию одним файлом.

    Это единственный способ довести работу до реального запуска, пока доступ к
    API Директа не получен: специалист забирает структуру, фразы, объявления и
    минус-слова и заводит кампанию через Коммандер или руками.

    Замечания к объявлениям попадают в отдельный столбец, а не отсеивают строки.
    Молча выбросить группу с длинным заголовком значило бы отдать неполную
    кампанию и не сказать об этом — человек узнал бы о пропаже уже в Директе.
    """
    project = await ProjectRepository(session, ctx).get_or_404(project_id)

    keywords = await _keywords(session, ctx, project_id)
    targeted = _targeted(keywords)
    groups = cluster(targeted)
    points, links = await _page_content(session, ctx, project_id)
    minus = ", ".join(f"-{row.word}" for row in await _minus_word_rows(session, ctx, project_id))

    # Кросс-минусовка считается по всему ядру сразу, а не внутри групп: фразы
    # перехватывают запросы друг у друга и через границу группы, и именно эти
    # пересечения заметить труднее всего.
    crossing = {
        item.phrase: ", ".join(f"-{word}" for word in item.minus_words)
        for item in cross_minus([k.phrase for k in targeted]).items
    }

    fallback = project.website_url or ""
    pages = await _landing_pages(session, ctx, project_id)
    rows: list[ExportRow] = []

    for group in groups:
        if not group.core:
            # Остаток — не группа под объявление. В выгрузку он не идёт, иначе
            # в Директе появилась бы группа без осмысленного объявления.
            continue

        landing = match_landing(group.core, pages, fallback=fallback)
        variants = build_variants(
            cluster_name=group.name,
            keywords=group.phrases,
            selling_points=points,
            region=project.primary_region,
            internal_links=links,
        )

        # Строка на пару «фраза × вариант»: Коммандер ждёт именно такую
        # таблицу, а объявления группы должны стоять рядом с её фразами.
        for index, draft in enumerate(variants, start=1):
            warnings = "; ".join(v.message for v in draft.violations)
            for phrase in group.phrases:
                rows.append(
                    ExportRow(
                        campaign=project.name,
                        group=group.name,
                        variant=str(index),
                        phrase=phrase,
                        title=draft.title,
                        title_2=draft.title_2 or "",
                        text=draft.text,
                        url=landing,
                        display_path=draft.display_path or "",
                        callouts=", ".join(draft.callouts),
                        sitelinks="; ".join(
                            f"{link.title} → {link.url}" for link in draft.sitelinks
                        ),
                        minus_words=minus,
                        phrase_minus_words=crossing.get(phrase, ""),
                        warnings=warnings,
                    )
                )

    body = to_csv(rows)
    name = file_name(project.name)

    return Response(
        content=body.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={
            # Имя файла русское, поэтому передаётся в кодированном виде: без
            # filename* браузер сохранит его как «download» или искажённо.
            "Content-Disposition": (
                f"attachment; filename=campaign.csv; filename*=UTF-8''{quote(name)}"
            )
        },
    )


async def _landing_pages(
    session: SessionDep, ctx: TenantDep, project_id: uuid.UUID
) -> list[LandingPage]:
    """Проверенные страницы проекта с заголовками — для подбора посадочной."""
    rows = list(
        (
            await session.execute(
                select(SiteAudit)
                .where(SiteAudit.organization_id == ctx.organization_id)
                .where(SiteAudit.project_id == project_id)
                .where(SiteAudit.status == ModuleStatus.COMPLETED)
                .order_by(SiteAudit.created_at.desc())
            )
        )
        .scalars()
        .all()
    )

    latest: dict[str, SiteAudit] = {}
    for row in rows:
        latest.setdefault(row.url, row)

    return [LandingPage(url=url, title=audit.page_title) for url, audit in latest.items()]


async def _page_content(
    session: SessionDep, ctx: TenantDep, project_id: uuid.UUID
) -> tuple[tuple[str, ...], tuple[tuple[str, str], ...]]:
    """Фрагменты предложения и разделы сайта из последней проверки.

    Берутся из одной и той же проверки: текст объявления и быстрые ссылки
    должны описывать одну версию страницы, иначе объявление обещает то, чего
    на ней уже нет.
    """
    audit = (
        await session.execute(
            select(SiteAudit)
            .where(SiteAudit.organization_id == ctx.organization_id)
            .where(SiteAudit.project_id == project_id)
            .where(SiteAudit.status == ModuleStatus.COMPLETED)
            .order_by(SiteAudit.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if audit is None:
        return (), ()

    links = tuple(
        (str(pair[0]), str(pair[1]))
        for pair in (audit.internal_links or [])
        if isinstance(pair, list) and len(pair) == 2
    )
    return tuple(audit.selling_points or []), links


@search_router.get("/search", response_model=SearchResult, summary="Поиск по проектам и фразам")
async def search(
    session: SessionDep,
    ctx: TenantDep,
    q: str = Query(min_length=2, max_length=120),
    limit: int = Query(default=10, ge=1, le=50),
) -> SearchResult:
    """Ищет по названиям проектов и по ключевым фразам.

    Поиск подстрочный, без морфологии. Для проектов и фраз этого достаточно:
    человек ищет то, что сам вводил, и помнит написание. Приводить запрос к
    основам здесь значило бы находить «ремонту» по запросу «ремонт» ценой того,
    что точное совпадение перестанет быть первым.

    Названия проектов сравниваются в Python, а не запросом к базе. Причина
    неочевидная и стоила бы молчаливо неработающего поиска: `lower()` в
    PostgreSQL при локали C не понижает регистр кириллицы — «Окна» остаётся
    «Окна», и поиск по-русски не находит ничего. Локаль задаётся при создании
    базы и на уже развёрнутых установках не меняется, поэтому полагаться на неё
    нельзя. Проектов у организации десятки, и сравнить их в памяти дешевле, чем
    зависеть от того, как когда-то создали базу.

    Фразы так не обрабатываются: они хранятся уже приведёнными к нижнему
    регистру при загрузке, и обычного LIKE достаточно — а их бывают тысячи.

    Найденная фраза показывается вместе с проектом: «остекление балконов» без
    указания, в каком проекте, не отвечает ни на один вопрос.
    """
    needle = q.strip().lower()
    pattern = f"%{needle}%"

    projects = [
        row
        for row in (await session.execute(ProjectRepository(session, ctx).scoped()))
        .scalars()
        .all()
        if needle in row.name.lower()
    ][:limit]

    keywords = list(
        (
            await session.execute(
                KeywordRepository(session, ctx)
                .scoped()
                .where(Keyword.phrase.like(pattern))
                .order_by(Keyword.frequency.desc().nullslast())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )

    names = {
        row.id: row.name
        for row in (await session.execute(ProjectRepository(session, ctx).scoped()))
        .scalars()
        .all()
    }

    return SearchResult(
        projects=[
            SearchProjectRead(id=row.id, name=row.name, status=row.status) for row in projects
        ],
        keywords=[
            SearchKeywordRead(
                phrase=row.phrase,
                frequency=row.frequency,
                intent=row.intent,
                project_id=row.project_id,
                project_name=names.get(row.project_id, "проект удалён"),
            )
            for row in keywords
        ],
    )
