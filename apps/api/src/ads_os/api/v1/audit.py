"""Аудит сайта: запуск и результат."""

from __future__ import annotations

import logging
import uuid
from urllib.parse import urlsplit

from fastapi import APIRouter, Query, status
from sqlalchemy import Select, select

from ...db.base import utcnow
from ...errors import AppError
from ...models import IssueDismissal, Project, SiteAudit
from ...models.activity import ActivityAction
from ...models.audit import ModuleStatus
from ...services.activity import record
from ...services.audit import (
    BLOCKING_ISSUE_KEYS,
    Issue,
    IssueKey,
    compare_issues,
    issues_from_stored,
)
from ...tenancy.repository import TenantRepository
from ...worker.tasks.audit import enqueue_site_audit
from ..deps import SessionDep, TenantDep, WriteDep
from ..schemas import (
    AuditChangesRead,
    AuditHistory,
    AuditHistoryItem,
    AuditIssueRead,
    AuditPageList,
    AuditPageRead,
    AuditRead,
    AuditStart,
    CategoryRead,
    DismissalCreate,
    DismissalList,
    DismissalRead,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["audit"])


class ProjectRepository(TenantRepository[Project]):
    model = Project


class DismissalRepository(TenantRepository[IssueDismissal]):
    model = IssueDismissal

    def scoped(self, *, include_deleted: bool = False) -> Select[tuple[IssueDismissal]]:
        return select(self.model).where(self.model.organization_id == self.ctx.organization_id)


class BlockingIssueError(AppError):
    """Попытка скрыть критическое замечание.

    Блокировка, которую можно спрятать, не является блокировкой. Если бы
    критическое замечание удавалось убрать с глаз, единственное, что мешает
    сжечь бюджет на неработающем сайте, снималось бы одним нажатием.
    """

    status_code = 422
    error_code = "issue_is_blocking"
    message = "Критическое замечание нельзя отметить неактуальным"


class UnknownIssueError(AppError):
    status_code = 404
    error_code = "unknown_issue"
    message = "Такой проверки не существует"


class AuditRepository(TenantRepository[SiteAudit]):
    model = SiteAudit

    def scoped(self, *, include_deleted: bool = False) -> Select[tuple[SiteAudit]]:
        # У аудита нет мягкого удаления: история хранится целиком и удаляется
        # только вместе с проектом.
        return select(self.model).where(self.model.organization_id == self.ctx.organization_id)


class ForeignPageError(AppError):
    """Попытка проверить страницу чужого сайта.

    Проверка ограничена доменом проекта не из осторожности, а по смыслу: это
    аудит посадочных страниц клиента. Без ограничения любой участник мог бы
    гонять краулер по произвольным адресам от имени сервиса.
    """

    status_code = 422
    error_code = "foreign_page"
    message = "Страница должна принадлежать сайту проекта"


class WebsiteMissingError(AppError):
    status_code = 422
    error_code = "website_missing"
    message = "У проекта не указан адрес сайта"


class QueueUnavailableError(AppError):
    """Очередь задач недоступна.

    Отдельная ошибка, а не общая «внутренняя»: недоступный Redis — это не
    дефект в коде, а состояние инфраструктуры. Пользователю нужно сказать, что
    повторить попытку имеет смысл, а дежурному — что чинить.
    """

    status_code = 503
    error_code = "queue_unavailable"
    message = "Фоновые задачи временно недоступны. Попробуйте позже"
    retryable = True


class AuditAlreadyRunningError(AppError):
    """Повторный запуск при уже идущем аудите.

    Не ошибка пользователя, а защита от лишней работы: краулер ходит по чужому
    сайту, и запускать его нажатием кнопки по нескольку раз не нужно.
    """

    status_code = 409
    error_code = "audit_already_running"
    message = "Аудит уже выполняется"
    retryable = True


@router.post(
    "/{project_id}/audit",
    response_model=AuditRead,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Запустить аудит сайта",
)
async def start_audit(
    project_id: uuid.UUID,
    session: SessionDep,
    ctx: WriteDep,
    payload: AuditStart | None = None,
) -> AuditRead:
    """Запускает проверку страницы.

    Без адреса проверяется главная страница проекта. С адресом — любая другая
    страница того же сайта: в кампании посадочных обычно несколько, и оценивать
    все по главной значит не проверять их вовсе.

    Отдельного списка страниц нет намеренно. Страница попадает в проект тем, что
    её проверили, — список страниц выводится из проверок. Отдельный справочник
    неизбежно разошёлся бы с ним: в нём остались бы адреса, которые никто не
    проверял, и он выглядел бы как охваченный объём.
    """
    project = await ProjectRepository(session, ctx).get_or_404(project_id)

    if not project.website_url:
        raise WebsiteMissingError()

    url = (payload.url if payload else None) or project.website_url
    if not _same_site(url, project.website_url):
        raise ForeignPageError()

    audits = AuditRepository(session, ctx)
    running = (
        await session.execute(
            audits.scoped()
            .where(SiteAudit.project_id == project_id)
            .where(SiteAudit.url == url)
            .where(SiteAudit.status.in_((ModuleStatus.QUEUED, ModuleStatus.RUNNING)))
        )
    ).scalars().first()

    if running is not None:
        raise AuditAlreadyRunningError()

    audit = SiteAudit(
        project_id=project_id,
        url=url,
        status=ModuleStatus.QUEUED,
        categories=[],
        issues=[],
    )
    await audits.add(audit)
    await session.flush()

    # Задача ставится в очередь после записи: если поставить раньше, воркер
    # может начать раньше, чем запись станет видимой.
    try:
        enqueue_site_audit(audit.id, url)
    except Exception as exc:
        # Запись удаляется явно, а не оставляется на откат транзакции. Аудит со
        # статусом «в очереди», которого в очереди нет, навсегда заблокировал бы
        # повторный запуск: проверка выше сочла бы его за идущий и вернула 409.
        # Полагаться здесь на чужую политику транзакций слишком хрупко.
        await session.delete(audit)
        await session.flush()
        logger.warning(
            "не удалось поставить аудит в очередь",
            extra={"project_id": str(project_id), "error": type(exc).__name__},
        )
        raise QueueUnavailableError() from exc

    await record(
        session,
        ctx,
        ActivityAction.AUDIT_STARTED,
        subject=project.name,
        actor_name=ctx.user_name,
        project_id=project_id,
        details={"адрес": url},
    )

    return _to_read(audit)


@router.get(
    "/{project_id}/audit",
    response_model=AuditRead | None,
    summary="Последний аудит сайта",
)
async def get_audit(
    project_id: uuid.UUID, session: SessionDep, ctx: TenantDep, url: str | None = None
) -> AuditRead | None:
    project = await ProjectRepository(session, ctx).get_or_404(project_id)

    # Без адреса показывается главная страница: с неё начинают, и открывать
    # экран на случайной из проверенных было бы неожиданно.
    page = url or project.website_url

    audits = AuditRepository(session, ctx)
    # Читаются две последние записи, а не одна: свежий результат почти всегда
    # смотрят с вопросом «стало ли лучше», и ответ на него требует предыдущей.
    rows = list(
        (
            await session.execute(
                audits.scoped()
                .where(SiteAudit.project_id == project_id)
                .where(SiteAudit.url == page)
                .order_by(SiteAudit.created_at.desc())
                .limit(2)
            )
        )
        .scalars()
        .all()
    )

    if not rows:
        return None

    latest = rows[0]
    previous = next(
        (row for row in rows[1:] if row.status is ModuleStatus.COMPLETED),
        None,
    )

    return _to_read(latest, previous, await _dismissals(session, ctx, project_id))


@router.get(
    "/{project_id}/audit/pages",
    response_model=AuditPageList,
    summary="Проверенные страницы проекта",
)
async def list_pages(
    project_id: uuid.UUID, session: SessionDep, ctx: TenantDep
) -> AuditPageList:
    """Страницы, которые проверяли, с последним результатом по каждой.

    Список выводится из проверок, а не из отдельного справочника: страница
    попадает в проект тем, что её проверили. Справочник неизбежно разошёлся бы
    с реальностью — в нём остались бы адреса, которых никто не касался, и он
    выглядел бы как охваченный объём.

    Главная страница показывается всегда, даже если её ещё не проверяли: иначе
    у нового проекта список был бы пустым и непонятно было бы, с чего начать.
    """
    project = await ProjectRepository(session, ctx).get_or_404(project_id)

    rows = list(
        (
            await session.execute(
                AuditRepository(session, ctx)
                .scoped()
                .where(SiteAudit.project_id == project_id)
                .order_by(SiteAudit.created_at.desc())
            )
        )
        .scalars()
        .all()
    )

    latest: dict[str, SiteAudit] = {}
    for row in rows:
        latest.setdefault(row.url, row)

    items: list[AuditPageRead] = []

    if project.website_url and project.website_url not in latest:
        items.append(
            AuditPageRead(
                url=project.website_url,
                is_primary=True,
                score=None,
                verdict=None,
                can_launch=False,
                status=ModuleStatus.NOT_STARTED,
                checked_at=None,
            )
        )

    for url, audit in latest.items():
        items.append(
            AuditPageRead(
                url=url,
                is_primary=url == project.website_url,
                score=audit.score,
                verdict=audit.verdict,
                can_launch=not any(
                    i.get("severity") == "critical" for i in (audit.issues or [])
                ),
                status=audit.status,
                checked_at=audit.finished_at or audit.created_at,
            )
        )

    # Главная всегда первой, остальные — от худшей оценки к лучшей: работать
    # начинают с той страницы, которая тянет вниз.
    items.sort(key=lambda item: (not item.is_primary, item.score if item.score is not None else -1))

    return AuditPageList(items=items, total=len(items))


@router.get(
    "/{project_id}/audits",
    response_model=AuditHistory,
    summary="История проверок сайта",
)
async def get_audit_history(
    project_id: uuid.UUID,
    session: SessionDep,
    ctx: TenantDep,
    limit: int = Query(default=20, ge=1, le=100),
) -> AuditHistory:
    """История запусков (v0.3 §62).

    Отвечает на один вопрос: помогли доработки сайта или нет. Поэтому рядом с
    баллом показывается его изменение относительно прошлой завершённой
    проверки — само по себе число «74» об этом ничего не говорит.
    """
    await ProjectRepository(session, ctx).get_or_404(project_id)

    audits = AuditRepository(session, ctx)
    rows = list(
        (
            await session.execute(
                audits.scoped()
                .where(SiteAudit.project_id == project_id)
                .order_by(SiteAudit.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )

    return AuditHistory(items=_with_deltas(rows), total=len(rows))


@router.get(
    "/{project_id}/audit/dismissals",
    response_model=DismissalList,
    summary="Скрытые замечания проекта",
)
async def list_dismissals(
    project_id: uuid.UUID, session: SessionDep, ctx: TenantDep
) -> DismissalList:
    await ProjectRepository(session, ctx).get_or_404(project_id)

    rows = await _dismissals(session, ctx, project_id)

    return DismissalList(
        items=[
            DismissalRead(
                issue_key=row.issue_key,
                reason=row.reason,
                dismissed_by=row.dismissed_by_name,
                created_at=row.created_at or utcnow(),
            )
            for row in rows.values()
        ],
        total=len(rows),
    )


@router.post(
    "/{project_id}/audit/dismissals",
    response_model=DismissalRead,
    status_code=status.HTTP_201_CREATED,
    summary="Отметить замечание неактуальным",
)
async def dismiss_issue(
    project_id: uuid.UUID, payload: DismissalCreate, session: SessionDep, ctx: WriteDep
) -> DismissalRead:
    """Скрывает замечание из рабочего списка.

    Балл и вердикт при этом не меняются. Балл — это измерение, а не
    договорённость: если бы его можно было поднять, отметив замечание
    неактуальным, он перестал бы что-либо значить, в том числе для клиента,
    которому его показывают.
    """
    project = await ProjectRepository(session, ctx).get_or_404(project_id)

    try:
        key = IssueKey(payload.issue_key)
    except ValueError as exc:
        raise UnknownIssueError() from exc

    if key in BLOCKING_ISSUE_KEYS:
        raise BlockingIssueError()

    existing = await _dismissals(session, ctx, project_id)
    row = existing.get(key.value)

    if row is None:
        row = IssueDismissal(
            project_id=project_id,
            issue_key=key.value,
            reason=payload.reason,
            dismissed_by_id=ctx.user_id,
            dismissed_by_name=ctx.user_name,
        )
        await DismissalRepository(session, ctx).add(row)
        await session.flush()
    else:
        # Повторное скрытие того же замечания — то же решение, а не второе.
        # Обновляется только пояснение: человек мог сформулировать точнее.
        row.reason = payload.reason

    await record(
        session,
        ctx,
        ActivityAction.ISSUE_DISMISSED,
        subject=project.name,
        actor_name=ctx.user_name,
        project_id=project_id,
        details={"замечание": key.value, "причина": payload.reason or "не указана"},
    )

    return DismissalRead(
        issue_key=row.issue_key,
        reason=row.reason,
        dismissed_by=row.dismissed_by_name,
        created_at=row.created_at or utcnow(),
    )


@router.delete(
    "/{project_id}/audit/dismissals/{issue_key}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Вернуть замечание в список",
)
async def restore_issue(
    project_id: uuid.UUID, issue_key: str, session: SessionDep, ctx: WriteDep
) -> None:
    project = await ProjectRepository(session, ctx).get_or_404(project_id)

    existing = await _dismissals(session, ctx, project_id)
    row = existing.get(issue_key)

    if row is None:
        raise UnknownIssueError()

    await session.delete(row)
    await session.flush()

    await record(
        session,
        ctx,
        ActivityAction.ISSUE_RESTORED,
        subject=project.name,
        actor_name=ctx.user_name,
        project_id=project_id,
        details={"замечание": issue_key},
    )


async def _dismissals(
    session: SessionDep, ctx: TenantDep, project_id: uuid.UUID
) -> dict[str, IssueDismissal]:
    rows = (
        (
            await session.execute(
                DismissalRepository(session, ctx)
                .scoped()
                .where(IssueDismissal.project_id == project_id)
            )
        )
        .scalars()
        .all()
    )
    return {row.issue_key: row for row in rows}


def _with_deltas(rows: list[SiteAudit]) -> list[AuditHistoryItem]:
    """Считает изменение балла относительно предыдущей завершённой проверки.

    Неудачные запуски в сравнении не участвуют: сайт, который не открылся, — не
    повод показать падение на семьдесят пунктов.
    """
    items: list[AuditHistoryItem] = []

    # Записи идут от новых к старым, поэтому предыдущая по времени — следующая
    # в списке.
    for index, audit in enumerate(rows):
        previous = next(
            (
                other
                for other in rows[index + 1 :]
                if other.status is ModuleStatus.COMPLETED and other.score is not None
            ),
            None,
        )

        delta = (
            audit.score - previous.score
            if audit.status is ModuleStatus.COMPLETED
            and audit.score is not None
            and previous is not None
            and previous.score is not None
            else None
        )

        changes = (
            compare_issues(
                issues_from_stored(previous.issues or []),
                issues_from_stored(audit.issues or []),
            )
            if audit.status is ModuleStatus.COMPLETED and previous is not None
            else None
        )

        items.append(
            AuditHistoryItem(
                id=audit.id,
                status=audit.status,
                score=audit.score,
                verdict=audit.verdict,
                can_launch=not any(
                    i.get("severity") == "critical" for i in (audit.issues or [])
                ),
                error_reason=audit.error_reason,
                finished_at=audit.finished_at,
                created_at=audit.created_at or utcnow(),
                score_delta=delta,
                fixed_count=len(changes.fixed) if changes else 0,
                appeared_count=len(changes.appeared) if changes else 0,
            )
        )

    return items


def _to_read(
    audit: SiteAudit,
    previous: SiteAudit | None = None,
    dismissals: dict[str, IssueDismissal] | None = None,
) -> AuditRead:
    changes: AuditChangesRead | None = None

    if audit.status is ModuleStatus.COMPLETED:
        if previous is None:
            # Первая завершённая проверка. «Сравнение не проводилось» и «ничего
            # не изменилось» — разные вещи, и путать их нельзя.
            changes = AuditChangesRead(compared=False, fixed=[], appeared=[], remaining=[])
        else:
            diff = compare_issues(
                issues_from_stored(previous.issues or []),
                issues_from_stored(audit.issues or []),
            )
            changes = AuditChangesRead(
                compared=True,
                fixed=[_issue(i) for i in diff.fixed],
                appeared=[_issue(i) for i in diff.appeared],
                remaining=[_issue(i) for i in diff.remaining],
            )

    return AuditRead(
        id=audit.id,
        project_id=audit.project_id,
        url=audit.url,
        final_url=audit.final_url,
        status=audit.status,
        score=audit.score,
        verdict=audit.verdict,
        metrica_counter=audit.metrica_counter,
        error_reason=audit.error_reason,
        categories=[CategoryRead(**c) for c in (audit.categories or [])],
        issues=[_stored_issue(i, dismissals or {}) for i in (audit.issues or [])],
        can_launch=not any(i.get("severity") == "critical" for i in (audit.issues or [])),
        changes=changes,
        started_at=audit.started_at,
        finished_at=audit.finished_at,
        created_at=audit.created_at or utcnow(),
    )


def _issue(issue: Issue) -> AuditIssueRead:
    return AuditIssueRead(
        key=issue.key.value,
        category=issue.category.value,
        severity=issue.severity.value,
        title=issue.title,
        action=issue.action,
    )


def _stored_issue(row: dict[str, object], dismissals: dict[str, IssueDismissal]) -> AuditIssueRead:
    """Находка из хранилища вместе с отметкой о скрытии.

    Скрытые находки не вырезаются из ответа, а помечаются. Убрать их совсем
    значило бы, что проверка их больше не находит, — а она находит, просто
    человек решил, что для этого проекта они не важны.
    """
    key = str(row.get("key") or "") or None
    dismissal = dismissals.get(key) if key else None

    return AuditIssueRead(
        key=key,
        category=str(row["category"]),
        severity=str(row["severity"]),
        title=str(row["title"]),
        action=str(row["action"]),
        dismissed=dismissal is not None,
        dismissed_reason=dismissal.reason if dismissal else None,
        dismissed_by=dismissal.dismissed_by_name if dismissal else None,
    )


def _same_site(url: str, site: str) -> bool:
    """Один ли это сайт.

    Сравниваются только домены, без учёта www и регистра: «example.ru» и
    «www.example.ru» для человека одно и то же, и требовать угадать написание
    было бы придиркой.
    """
    return _host(url) == _host(site) and urlsplit(url).scheme in ("http", "https")


def _host(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host
