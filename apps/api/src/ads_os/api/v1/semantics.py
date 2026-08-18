"""Семантика: импорт списка, разбор, группы, минус-слова."""

from __future__ import annotations

import base64
import binascii
import uuid
from collections import defaultdict
from urllib.parse import quote

from fastapi import APIRouter, Query, Response, status
from sqlalchemy import Select, select

from ...config import get_settings
from ...errors import AppError, NotFoundError
from ...models import Keyword, KeywordBrief, MinusWord, Project, SiteAudit
from ...models.activity import ActivityAction
from ...models.audit import ModuleStatus
from ...models.collection import KeywordCollection
from ...services import keyword_store, niches, profile, utm, wordstat_quota
from ...services.activity import record
from ...services.ads import build_variants
from ...services.cleanup import REASON_HINTS, REASON_LABELS, Reason, reason_for
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
from ...services.tables import UnreadableFileError, to_lines
from ...services.wordstat import WHY_MANUAL, Brief, masks, steps
from ...tenancy.repository import TenantRepository
from ...worker.tasks.collect import build_masks, enqueue_collection
from ..deps import SessionDep, TenantDep, WriteDep
from ..schemas import (
    AdDraftList,
    AdDraftRead,
    AdViolationRead,
    AnswersUpdate,
    BriefRead,
    BriefUpdate,
    CleanupGroupRead,
    CleanupResult,
    ClientProfileRead,
    ClusterList,
    ClusterRead,
    CollectionMaskRead,
    CollectionRead,
    CrossMinusRead,
    CrossMinusResultRead,
    DuplicateRead,
    GroupChangeRead,
    GroupList,
    GroupMove,
    GroupPhraseRead,
    GroupRead,
    GroupRename,
    ImportSummary,
    KeywordFileImport,
    KeywordImport,
    KeywordList,
    KeywordRead,
    KeywordUpdate,
    MaskRead,
    MinusWordBulkCreate,
    MinusWordCreate,
    MinusWordList,
    MinusWordRead,
    MinusWordSuggestionRead,
    OnboardingApply,
    OnboardingRead,
    QuestionRead,
    SearchKeywordRead,
    SearchProjectRead,
    SearchResult,
    SitelinkRead,
    UtmNotesRead,
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


class BadFileError(AppError):
    status_code = 422
    error_code = "bad_file"
    message = "Не удалось прочитать файл. Подойдёт xlsx, csv или txt."


class BriefRepository(TenantRepository[KeywordBrief]):
    model = KeywordBrief

    def scoped(self, *, include_deleted: bool = False) -> Select[tuple[KeywordBrief]]:
        return select(self.model).where(
            self.model.organization_id == self.ctx.organization_id
        )


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
    return await _import(project_id, payload.text, session, ctx)


@router.post(
    "/{project_id}/keywords/import-file",
    response_model=ImportSummary,
    summary="Загрузить выгрузку файлом",
)
async def import_keywords_file(
    project_id: uuid.UUID, payload: KeywordFileImport, session: SessionDep, ctx: WriteDep
) -> ImportSummary:
    """Принимает файл выгрузки: xlsx из Вордстата, csv из Key Collector, txt.

    Формат не спрашивается. Вордстат отдаёт xlsx, Key Collector — то xlsx, то
    csv, а кто-то просто копирует колонку в блокнот; требовать привести файл к
    одному виду значит переложить на человека работу, которая занимает у
    программы миллисекунды, а у него — каждый раз по десять минут.
    """
    try:
        content = base64.b64decode(payload.content_base64, validate=True)
    except (ValueError, binascii.Error) as error:
        raise BadFileError() from error

    try:
        text = to_lines(content, filename=payload.filename)
    except UnreadableFileError as error:
        raise BadFileError(str(error)) from error

    return await _import(project_id, text, session, ctx)


async def _import(
    project_id: uuid.UUID, text: str, session: SessionDep, ctx: WriteDep
) -> ImportSummary:
    """Общий путь для вставленного текста и для файла.

    Именно общий: у выгрузки и у вставки не должно быть двух разных разборов,
    иначе они разойдутся, и расхождение обнаружится на чужом файле в неудобный
    момент.
    """
    project = await ProjectRepository(session, ctx).get_or_404(project_id)

    parsed = parse_list(text)
    if len(parsed) > MAX_KEYWORDS_PER_IMPORT:
        raise TooManyKeywordsError()

    lines = sum(1 for line in text.splitlines() if line.strip())
    skipped = max(0, lines - len(parsed))

    existing = {row.phrase: row for row in await _keywords(session, ctx, project_id)}
    extra = await _minus_words_set(session, ctx, project_id)

    added = updated = 0

    for item in parsed:
        row = existing.get(item.phrase)

        if row is None:
            result = classify(item.phrase, extra_irrelevant=extra, region=project.primary_region)
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
                result = classify(
                    item.phrase, extra_irrelevant=extra, region=project.primary_region
                )
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
        cleaned=_cleanup_groups(rows, minus_words=extra),
    )


def _cleanup_groups(rows: list[Keyword], *, minus_words: frozenset[str]) -> list[CleanupGroupRead]:
    """Разбивка нецелевых фраз по причинам.

    Нужна ровно для одного вопроса, который человек задаёт после загрузки:
    «а не выкинуло ли оно лишнего». Ответить на него можно только показав, что
    именно и по какой причине ушло — с примерами, которые видно с экрана.
    """
    by_reason: dict[Reason, list[str]] = defaultdict(list)

    for row in rows:
        if row.intent is not Intent.IRRELEVANT or row.is_manual:
            continue
        reason = reason_for(row.trigger, minus_words=minus_words)
        if reason is None:
            continue
        by_reason[reason].append(row.phrase)

    groups = [
        CleanupGroupRead(
            reason=reason,
            label=REASON_LABELS[reason],
            hint=REASON_HINTS[reason],
            phrases=len(phrases),
            examples=sorted(phrases)[:3],
        )
        for reason, phrases in by_reason.items()
    ]
    groups.sort(key=lambda group: (-group.phrases, group.label))
    return groups


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

    minus = await _minus_words_set(session, ctx, project_id)
    return KeywordList(
        items=[_to_read(row, minus_words=minus) for row in rows[:limit]], total=len(rows)
    )


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
    "/{project_id}/onboarding",
    response_model=OnboardingRead,
    summary="Что прочитано с сайта и что осталось спросить",
)
async def get_onboarding(
    project_id: uuid.UUID, session: SessionDep, ctx: TenantDep
) -> OnboardingRead:
    """Анкета клиента с его же сайта плюс вопросы, на которые сайт не отвечает.

    Разделение принципиальное. Название, город, услуги и контакты на странице
    написаны — их незачем спрашивать. Средний чек, маржа и то, чего клиент не
    делает, на сайте не пишут никогда, и подставить сюда правдоподобные числа
    значило бы построить весь расчёт экономики на выдумке.
    """
    project = await ProjectRepository(session, ctx).get_or_404(project_id)
    audit = await _last_audit(session, ctx, project_id)
    brief = await _brief_row(session, ctx, project_id)

    data = profile.from_stored(audit.client_profile if audit else None)
    answers = {key: str(value) for key, value in (brief.answers if brief else {}).items()}

    return OnboardingRead(
        has_audit=audit is not None,
        source_url=(audit.final_url or audit.url) if audit else None,
        profile=ClientProfileRead(**data.as_dict()),
        filled=data.filled,
        can_apply=_appliable(project, data, brief),
        questions=[
            QuestionRead(key=q.key, text=q.text, why=q.why, answer=answers.get(q.key, ""))
            for q in profile.open_questions(data)
        ],
        niche_questions=[
            QuestionRead(key=q.key, text=q.text, why=q.why, answer=answers.get(q.key, ""))
            for q in profile.niche_questions(project.niche or data.niche_key)
        ],
    )


@router.put(
    "/{project_id}/onboarding/answers",
    response_model=OnboardingRead,
    summary="Записать ответы клиента",
)
async def save_answers(
    project_id: uuid.UUID, payload: AnswersUpdate, session: SessionDep, ctx: WriteDep
) -> OnboardingRead:
    """Сохраняет ответы на вопросы, на которые сайт не отвечает.

    Приходят только изменённые: поля сохраняются по мере заполнения, и
    присылать каждый раз всю анкету значило бы затирать ответ, который в этот
    момент правят в соседней вкладке.

    Пустой ответ стирает прежний. Это не оплошность: человек, стерший строку,
    именно этого и хотел, а «пустое не сохраняем» превратило бы удаление в
    невозможное действие.
    """
    await ProjectRepository(session, ctx).get_or_404(project_id)

    row = await _brief_row(session, ctx, project_id)
    if row is None:
        row = KeywordBrief(project_id=project_id)
        await BriefRepository(session, ctx).add(row)
        await session.flush()

    answers = dict(row.answers or {})
    for key, value in payload.answers.items():
        text = value.strip()[:2000]
        if text:
            answers[key] = text
        else:
            answers.pop(key, None)

    row.answers = answers

    # Ответ «чего клиент не делает» — это ровно то же, что поле «чего не
    # делаем» в брифе. Спрашивать дважды об одном значит выглядеть системой,
    # которая не слушает: заполняем, пока поле пустое.
    not_selling = answers.get("not_selling", "").strip()
    if not_selling and not row.excludes:
        row.excludes = not_selling

    await session.flush()

    return await get_onboarding(project_id, session, ctx)


@router.post(
    "/{project_id}/onboarding/apply",
    response_model=OnboardingRead,
    summary="Перенести прочитанное в проект",
)
async def apply_onboarding(
    project_id: uuid.UUID, payload: OnboardingApply, session: SessionDep, ctx: WriteDep
) -> OnboardingRead:
    """Переносит выбранные поля анкеты в проект и бриф.

    Только по явному выбору и только в пустые поля. Разбор чужой страницы
    ошибается, и молча проставленный не тот город — это месяц рекламы в чужом
    регионе, который по интерфейсу, ничего не спросившему, не заметить.
    """
    project = await ProjectRepository(session, ctx).get_or_404(project_id)
    audit = await _last_audit(session, ctx, project_id)
    data = profile.from_stored(audit.client_profile if audit else None)

    changed: dict[str, str] = {}

    if payload.region and data.city and not project.primary_region:
        project.primary_region = data.city
        changed["регион"] = data.city

    if payload.niche and data.niche_key and not project.niche:
        project.niche = data.niche_key
        changed["ниша"] = data.niche_label or data.niche_key

    if payload.brief and (data.services or data.city):
        row = await _brief_row(session, ctx, project_id)
        if row is None:
            row = KeywordBrief(project_id=project_id)
            await BriefRepository(session, ctx).add(row)
        if data.services and not row.sells:
            row.sells = ", ".join(data.services)
            changed["что продаём"] = row.sells[:60]
        if data.city and not row.cities:
            row.cities = data.city

    await session.flush()

    if changed:
        await record(
            session,
            ctx,
            ActivityAction.PROJECT_UPDATED,
            subject=project.name,
            actor_name=ctx.user_name,
            project_id=project_id,
            details={"заполнено с сайта": ", ".join(changed)},
        )

    return await get_onboarding(project_id, session, ctx)


def _appliable(
    project: Project, data: profile.ClientProfile, brief: KeywordBrief | None
) -> list[str]:
    """Что из прочитанного ещё не перенесено.

    Уже заполненное не предлагается: подсказка, повторяющая сделанное, — это не
    помощь, а шум, из-за которого пропускают настоящие подсказки.
    """
    ready: list[str] = []
    if data.city and not project.primary_region:
        ready.append("region")
    if data.niche_key and not project.niche:
        ready.append("niche")
    if data.services and not (brief and brief.sells):
        ready.append("brief")
    return ready


async def _last_audit(
    session: SessionDep, ctx: TenantDep, project_id: uuid.UUID
) -> SiteAudit | None:
    return (
        await session.execute(
            select(SiteAudit)
            .where(SiteAudit.organization_id == ctx.organization_id)
            .where(SiteAudit.project_id == project_id)
            .where(SiteAudit.status == ModuleStatus.COMPLETED)
            .order_by(SiteAudit.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


@router.get("/{project_id}/brief", response_model=BriefRead, summary="Бриф и маски для Вордстата")
async def get_brief(project_id: uuid.UUID, session: SessionDep, ctx: TenantDep) -> BriefRead:
    """Отдаёт бриф вместе с тем, что из него следует.

    Маски считаются на лету, а не хранятся. Они выводятся из брифа, ниши и
    региона; сохранённые разошлись бы с ними при первой же правке, и человек
    пошёл бы собирать запросы по списку, которого уже нет.
    """
    project = await ProjectRepository(session, ctx).get_or_404(project_id)
    row = await _brief_row(session, ctx, project_id)

    return _brief_read(project, row)


@router.put("/{project_id}/brief", response_model=BriefRead, summary="Сохранить бриф")
async def save_brief(
    project_id: uuid.UUID, payload: BriefUpdate, session: SessionDep, ctx: WriteDep
) -> BriefRead:
    project = await ProjectRepository(session, ctx).get_or_404(project_id)
    row = await _brief_row(session, ctx, project_id)

    if row is None:
        row = KeywordBrief(project_id=project_id)
        await BriefRepository(session, ctx).add(row)

    row.sells = payload.sells.strip()
    row.synonyms = payload.synonyms.strip()
    row.excludes = payload.excludes.strip()
    row.cities = payload.cities.strip()
    await session.flush()

    return _brief_read(project, row)


async def _brief_row(
    session: SessionDep, ctx: TenantDep, project_id: uuid.UUID
) -> KeywordBrief | None:
    stmt = BriefRepository(session, ctx).scoped().where(KeywordBrief.project_id == project_id)
    return (await session.execute(stmt)).scalar_one_or_none()


def _brief_read(project: Project, row: KeywordBrief | None) -> BriefRead:
    brief = Brief(
        sells=row.sells if row else "",
        synonyms=row.synonyms if row else "",
        excludes=row.excludes if row else "",
        cities=row.cities if row else "",
    )
    niche_words = niches.minus_words(niches.get(project.niche))

    return BriefRead(
        sells=brief.sells,
        synonyms=brief.synonyms,
        excludes=brief.excludes,
        cities=brief.cities,
        region=project.primary_region,
        masks=[
            MaskRead(query=mask.query, purpose=mask.purpose)
            for mask in masks(
                brief, niche_words=niche_words, region=project.primary_region
            )
        ],
        steps=list(steps(project.primary_region)),
        why_manual=WHY_MANUAL,
    )


@router.post(
    "/{project_id}/keywords/recheck",
    response_model=CleanupResult,
    summary="Перепроверить ядро заново",
)
async def recheck_keywords(
    project_id: uuid.UUID, session: SessionDep, ctx: WriteDep
) -> CleanupResult:
    """Прогоняет уже загруженные фразы через разбор ещё раз.

    Нужно после того, как изменилось что-то, от чего разбор зависит: регион
    проекта, минус-слова, сам словарь. Без этого проект, загруженный вчера,
    навсегда остался бы с прежней разметкой, а человек видел бы улучшения
    только на новых проектах и не понимал, почему.

    Ручные решения не трогаются: специалист уже сказал своё слово.
    """
    project = await ProjectRepository(session, ctx).get_or_404(project_id)

    extra = await _minus_words_set(session, ctx, project_id)
    rows = await _keywords(session, ctx, project_id)

    changed = 0
    for row in rows:
        if row.is_manual:
            continue
        result = classify(row.phrase, extra_irrelevant=extra, region=project.primary_region)
        if row.intent is not result.intent or row.trigger != result.trigger:
            changed += 1
        row.intent = result.intent
        row.trigger = result.trigger

    clusters = _recluster(rows)
    await session.flush()

    return _cleanup_result(rows, affected=changed, clusters=clusters)


@router.delete(
    "/{project_id}/keywords/irrelevant",
    response_model=CleanupResult,
    summary="Убрать все нецелевые фразы",
)
async def drop_irrelevant(
    project_id: uuid.UUID, session: SessionDep, ctx: WriteDep
) -> CleanupResult:
    """Удаляет из ядра всё, что помечено нецелевым.

    Отдельное действие, а не часть загрузки. Разметка ошибается в обе стороны,
    и молча удалять по ней — значит лишить человека возможности заметить
    ошибку: он увидел бы только итог, уже без того, что пропало.

    Фразы, тип которых поставил человек, остаются даже если он сам отнёс их к
    нецелевым: удалять чужое решение по кнопке «убрать мусор» — не то, чего от
    неё ждут. Такую фразу видно в списке, и убрать её можно поштучно.
    """
    project = await ProjectRepository(session, ctx).get_or_404(project_id)

    rows = await _keywords(session, ctx, project_id)
    doomed = [row for row in rows if row.intent is Intent.IRRELEVANT and not row.is_manual]

    for row in doomed:
        await session.delete(row)
    await session.flush()

    remaining = [row for row in rows if row not in doomed]
    clusters = _recluster(remaining)
    await session.flush()

    if doomed:
        await record(
            session,
            ctx,
            ActivityAction.KEYWORDS_CLEANED,
            subject=project.name,
            actor_name=ctx.user_name,
            project_id=project_id,
            details={"удалено": str(len(doomed))},
        )

    return _cleanup_result(remaining, affected=len(doomed), clusters=clusters)


def _cleanup_result(rows: list[Keyword], *, affected: int, clusters: int) -> CleanupResult:
    return CleanupResult(
        affected=affected,
        remaining=len(rows),
        commercial=sum(1 for r in rows if r.intent is Intent.COMMERCIAL),
        informational=sum(1 for r in rows if r.intent is Intent.INFORMATIONAL),
        irrelevant=sum(1 for r in rows if r.intent is Intent.IRRELEVANT),
        clusters=clusters,
    )


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
            word=item.word,
            phrases=item.phrases,
            examples=list(item.examples),
            reason=item.reason,
            reason_label=REASON_LABELS[item.reason] if item.reason else None,
        )
        for item in suggest_minus_words(
            [ParsedKeyword(row.phrase, row.frequency) for row in keywords],
            extra_irrelevant=frozenset(saved),
            region=project.primary_region,
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
    await _reclassify(session, ctx, project, extra_irrelevant=frozenset(extra))

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


@router.post(
    "/{project_id}/minus-words/bulk",
    response_model=MinusWordList,
    status_code=status.HTTP_201_CREATED,
    summary="Добавить несколько минус-слов",
)
async def add_minus_words(
    project_id: uuid.UUID, payload: MinusWordBulkCreate, session: SessionDep, ctx: WriteDep
) -> MinusWordList:
    """Принимает список слов и перепроверяет ядро один раз, а не по разу на слово.

    Так работают подсказки: стартовый набор ниши и слова, повторённые в других
    проектах, — это десятки слов, которые принимают одним решением.
    """
    project = await ProjectRepository(session, ctx).get_or_404(project_id)

    rows = await _minus_word_rows(session, ctx, project_id)
    known = {row.word for row in rows}
    added: list[str] = []

    for raw in payload.words:
        word = raw.strip().lower()
        if not word or word in known:
            continue
        known.add(word)
        added.append(word)
        await MinusWordRepository(session, ctx).add(MinusWord(project_id=project_id, word=word))

    await session.flush()

    if added:
        await _reclassify(session, ctx, project, extra_irrelevant=frozenset(known))
        await record(
            session,
            ctx,
            ActivityAction.MINUS_WORD_ADDED,
            subject=project.name,
            actor_name=ctx.user_name,
            project_id=project_id,
            details={"слов": str(len(added)), "первое": added[0]},
        )

    return await list_minus_words(project_id, session, ctx)


async def _reclassify(
    session: SessionDep, ctx: TenantDep, project: Project, *, extra_irrelevant: frozenset[str]
) -> None:
    """Перепроверяет ядро после изменения минус-списка.

    Обязательна: минус-слово, не изменившее ни одной фразы, выглядит как
    принятое решение, хотя не сделало ничего. Ручные решения не трогаются.
    """
    for keyword in await _keywords(session, ctx, project.id):
        if keyword.is_manual:
            continue
        result = classify(
            keyword.phrase, extra_irrelevant=extra_irrelevant, region=project.primary_region
        )
        keyword.intent = result.intent
        keyword.trigger = result.trigger

    await session.flush()


@router.delete(
    "/{project_id}/minus-words/{minus_word_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Убрать минус-слово",
)
async def delete_minus_word(
    project_id: uuid.UUID, minus_word_id: uuid.UUID, session: SessionDep, ctx: WriteDep
) -> None:
    project = await ProjectRepository(session, ctx).get_or_404(project_id)

    rows = await _minus_word_rows(session, ctx, project_id)
    row = next((r for r in rows if r.id == minus_word_id), None)
    if row is None:
        raise KeywordNotFoundError()

    await session.delete(row)
    await session.flush()

    remaining = frozenset(r.word for r in rows if r.id != minus_word_id)
    await _reclassify(session, ctx, project, extra_irrelevant=remaining)


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


def _to_read(row: Keyword, *, minus_words: frozenset[str] = frozenset()) -> KeywordRead:
    reason = None if row.is_manual else reason_for(row.trigger, minus_words=minus_words)
    return KeywordRead(
        id=row.id,
        phrase=row.phrase,
        frequency=row.frequency,
        intent=row.intent,
        intent_label=INTENT_LABELS[row.intent],
        trigger=row.trigger,
        reason=reason,
        reason_label=REASON_LABELS[reason] if reason else None,
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
    # Ссылка показывается уже размеченной: именно она уедет в кампанию, и
    # увидеть её человек должен до выгрузки, а не после запуска.
    template = utm.UtmTemplate()

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
                landing_url=utm.tag(
                    match_landing(group.core, pages, fallback=fallback),
                    template,
                    campaign_name=utm.slug(project.name),
                ),
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
        utm=UtmNotesRead(
            example=utm.preview(fallback or "https://site.ru/", template,
                                campaign_name=utm.slug(project.name)),
            notes=list(utm.NOTES),
        ),
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
    # Разметка проставляется здесь, а не на экране: файл уходит прямо в
    # Коммандер, и размечать его потом уже некому.
    template = utm.UtmTemplate()
    rows: list[ExportRow] = []

    for group in groups:
        if not group.core:
            # Остаток — не группа под объявление. В выгрузку он не идёт, иначе
            # в Директе появилась бы группа без осмысленного объявления.
            continue

        landing = utm.tag(
            match_landing(group.core, pages, fallback=fallback),
            template,
            campaign_name=utm.slug(project.name),
        )
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


# ─── Сбор частотностей ────────────────────────────────────────────────────────


class CollectionRepository(TenantRepository[KeywordCollection]):
    model = KeywordCollection


class CollectionRunningError(AppError):
    """Сбор уже идёт.

    Второй запуск поверх первого не ускорил бы работу, а поделил бы на двоих ту
    же сотню запросов в час — и оба сбора встали бы на середине.
    """

    status_code = 409
    error_code = "collection_running"
    message = "Сбор уже идёт. Дождитесь его окончания или остановите"


class NothingToCollectError(AppError):
    status_code = 422
    error_code = "nothing_to_collect"
    message = "Сначала заполните бриф: из него строятся маски для сбора"


@router.post(
    "/{project_id}/keywords/collect",
    response_model=CollectionRead,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Собрать частотности по маскам",
)
async def start_collection(
    project_id: uuid.UUID, session: SessionDep, ctx: WriteDep
) -> CollectionRead:
    """Ставит сбор в очередь.

    Ответ приходит сразу и со статусом «в очереди»: сбор идёт минутами, а при
    кончившейся квоте — часами. Держать соединение открытым всё это время
    незачем, а показывать «загрузка» на час — тем более.
    """
    project = await ProjectRepository(session, ctx).get_or_404(project_id)

    running = await _running_collection(session, ctx, project_id)
    if running is not None:
        raise CollectionRunningError()

    brief = await _brief_row(session, ctx, project_id)
    masks = build_masks(project, brief)
    if not masks:
        raise NothingToCollectError()

    collection = KeywordCollection(project_id=project_id, masks=masks)
    await CollectionRepository(session, ctx).add(collection)
    await session.flush()

    # Задача ставится после фиксации записи: воркер начинает мгновенно и не
    # найдёт того, чего ещё нет в базе.
    await session.commit()
    enqueue_collection(collection.id)

    return await _collection_read(collection)


@router.get(
    "/{project_id}/keywords/collect",
    response_model=CollectionRead,
    summary="Ход сбора частотностей",
)
async def get_collection(
    project_id: uuid.UUID, session: SessionDep, ctx: TenantDep
) -> CollectionRead:
    await ProjectRepository(session, ctx).get_or_404(project_id)

    # include_deleted: у записи о сборе нет мягкого удаления — она живёт
    # ровно столько же, сколько проект, и прятать её отдельно не от чего.
    stmt = (
        CollectionRepository(session, ctx)
        .scoped(include_deleted=True)
        .where(KeywordCollection.project_id == project_id)
        .order_by(KeywordCollection.created_at.desc())
        .limit(1)
    )
    collection = (await session.execute(stmt)).scalar_one_or_none()

    return await _collection_read(collection)


async def _running_collection(
    session: SessionDep, ctx: TenantDep, project_id: uuid.UUID
) -> KeywordCollection | None:
    stmt = (
        CollectionRepository(session, ctx)
        .scoped(include_deleted=True)
        .where(KeywordCollection.project_id == project_id)
        .where(KeywordCollection.status.in_([ModuleStatus.QUEUED, ModuleStatus.RUNNING]))
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def _collection_read(collection: KeywordCollection | None) -> CollectionRead:
    """Ход сбора вместе с остатком квоты.

    Остаток спрашивается здесь, а не хранится в записи: он общий на весь
    сервис и меняется от чужих сборов тоже. Сохранённое число разошлось бы с
    действительностью через минуту после записи.
    """
    settings = get_settings()

    blocked = ""
    if settings.wordstat_provider != "yandex":
        blocked = (
            "Сбор частотностей не подключён. Пока источника нет, частотности "
            "берутся из выгрузки, сделанной вручную."
        )

    left = 0
    if not blocked:
        try:
            left = await wordstat_quota.get_quota().remaining()
        except Exception:
            left = 0

    if collection is None:
        return CollectionRead(exists=False, quota_left=left, blocked_reason=blocked)

    masks = [CollectionMaskRead(**item) for item in (collection.masks or [])]

    return CollectionRead(
        exists=True,
        id=collection.id,
        status=collection.status,
        masks=masks,
        done_count=sum(1 for m in masks if m.state != "pending"),
        total_count=len(masks),
        added=collection.added,
        updated=collection.updated,
        requests=collection.requests,
        quota_left=left,
        resumes_at=collection.resumes_at,
        error_reason=collection.error_reason,
        started_at=collection.started_at,
        finished_at=collection.finished_at,
        blocked_reason=blocked,
    )


# ─── Группы: чтение и правка ──────────────────────────────────────────────────


@router.get(
    "/{project_id}/keywords/groups",
    response_model=GroupList,
    summary="Группы вместе с фразами",
)
async def list_groups(
    project_id: uuid.UUID, session: SessionDep, ctx: TenantDep
) -> GroupList:
    """Отдаёт группы так, как они сейчас лежат в ядре.

    Читаются из базы, а не пересчитываются на лету. Раньше было наоборот, и это
    делало правку невозможной в принципе: человек переносил фразу, а следующее
    открытие экрана показывало прежнюю раскладку — расчёт не знал о его
    решении и выводил группы заново.
    """
    await ProjectRepository(session, ctx).get_or_404(project_id)

    rows = await _keywords(session, ctx, project_id)
    targeted = [row for row in rows if row.intent is not Intent.IRRELEVANT]

    groups: dict[str, list[Keyword]] = {}
    ungrouped: list[Keyword] = []

    for row in targeted:
        if row.cluster_name:
            groups.setdefault(row.cluster_name, []).append(row)
        else:
            ungrouped.append(row)

    items = [
        GroupRead(
            name=name,
            phrases=[_group_phrase(row) for row in _by_frequency(members)],
            total_frequency=sum(row.frequency or 0 for row in members),
            manual=any(row.cluster_manual for row in members),
        )
        for name, members in groups.items()
    ]
    # Крупные группы сверху: с них начинают работу, и они же решают структуру
    # кампании.
    items.sort(key=lambda group: group.total_frequency, reverse=True)

    return GroupList(
        items=items,
        total=len(items),
        ungrouped=[_group_phrase(row) for row in _by_frequency(ungrouped)],
    )


@router.post(
    "/{project_id}/keywords/groups/move",
    response_model=GroupChangeRead,
    summary="Перенести фразы в группу",
)
async def move_phrases(
    project_id: uuid.UUID, payload: GroupMove, session: SessionDep, ctx: WriteDep
) -> GroupChangeRead:
    project = await ProjectRepository(session, ctx).get_or_404(project_id)

    change = await keyword_store.move_to_group(
        session, payload.keyword_ids, project_id=project.id, group=payload.group
    )

    await record(
        session,
        ctx,
        ActivityAction.KEYWORDS_CLEANED,
        subject=project.name,
        actor_name=ctx.user_name,
        project_id=project.id,
        details={"перенесено фраз": str(change.moved), "группа": payload.group or "без группы"},
    )

    return GroupChangeRead(moved=change.moved, groups=change.groups)


@router.patch(
    "/{project_id}/keywords/groups/{name}",
    response_model=GroupChangeRead,
    summary="Переименовать группу",
)
async def rename_group(
    project_id: uuid.UUID,
    name: str,
    payload: GroupRename,
    session: SessionDep,
    ctx: WriteDep,
) -> GroupChangeRead:
    project = await ProjectRepository(session, ctx).get_or_404(project_id)

    change = await keyword_store.rename_group(
        session, project_id=project.id, old=name, new=payload.name
    )
    if change.moved == 0:
        raise NotFoundError()

    return GroupChangeRead(moved=change.moved, groups=change.groups)


@router.delete(
    "/{project_id}/keywords/groups/{name}",
    response_model=GroupChangeRead,
    summary="Распустить группу",
)
async def dissolve_group(
    project_id: uuid.UUID, name: str, session: SessionDep, ctx: WriteDep
) -> GroupChangeRead:
    """Распускает группу: фразы остаются, группы больше нет.

    Фразы возвращаются расчёту, а не помечаются ручными. Человек сказал «эта
    группа неверна», а не «эти фразы не нужны в структуре».
    """
    project = await ProjectRepository(session, ctx).get_or_404(project_id)

    change = await keyword_store.dissolve_group(session, project_id=project.id, name=name)
    if change.moved == 0:
        raise NotFoundError()

    return GroupChangeRead(moved=change.moved, groups=change.groups)


@router.post(
    "/{project_id}/keywords/groups/recluster",
    response_model=GroupChangeRead,
    summary="Пересобрать группы",
)
async def recluster_groups(
    project_id: uuid.UUID, session: SessionDep, ctx: WriteDep
) -> GroupChangeRead:
    """Раскладывает фразы заново.

    Ручные группы не трогает: пересчёт, стирающий чужую работу, — это причина
    больше никогда не нажимать эту кнопку.
    """
    project = await ProjectRepository(session, ctx).get_or_404(project_id)

    groups = await keyword_store.recluster(session, project_id=project.id)
    rows = await _keywords(session, ctx, project_id)

    return GroupChangeRead(
        moved=sum(1 for row in rows if not row.cluster_manual and row.cluster_name),
        groups=groups,
    )


def _group_phrase(row: Keyword) -> GroupPhraseRead:
    return GroupPhraseRead(
        id=row.id,
        phrase=row.phrase,
        frequency=row.frequency,
        intent=row.intent,
        manual=row.cluster_manual,
    )


def _by_frequency(rows: list[Keyword]) -> list[Keyword]:
    """Частые фразы сверху: по ним и судят о группе."""
    return sorted(rows, key=lambda row: (-(row.frequency or 0), row.phrase))
