"""Когда система обязана сообщить сама.

Правила отбора здесь, а не в задаче проверки: их придётся менять чаще, чем
саму проверку, и держать их в одном месте — единственный способ не получить
три разных представления о том, что считать поломкой.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession as DbSession

from ..models.notification import Notification, NotificationKind, NotificationLevel
from ..services.audit import Issue, IssueChanges, Severity

#: Насколько должна упасть оценка, чтобы это считалось событием. Колебание в
#: два-три пункта — это обычный разброс: сайт мог отвечать чуть медленнее.
#: Уведомление о таком приучает не читать уведомления.
SIGNIFICANT_DROP = 15


@dataclass(frozen=True, slots=True)
class Alert:
    """Готовое уведомление до записи в базу."""

    kind: NotificationKind
    level: NotificationLevel
    title: str
    body: str
    dedup_key: str


def evaluate_audit(
    *,
    changes: IssueChanges | None,
    score: int | None,
    previous_score: int | None,
    failed_reason: str | None = None,
) -> Alert | None:
    """Решает, есть ли о чём сообщать по итогам проверки сайта.

    Возвращает не более одного уведомления. Три сообщения об одной поломке —
    это не втрое больше информации, а втрое больше шума: человек читает первое
    и перестаёт читать остальные.
    """
    if failed_reason:
        return Alert(
            kind=NotificationKind.SITE_UNREACHABLE,
            level=NotificationLevel.CRITICAL,
            title="Сайт не открылся при проверке",
            body=(
                f"{failed_reason}. Если реклама уже идёт, клики оплачиваются, а "
                "посетители не попадают на страницу. Проверьте сайт и адрес в проекте."
            ),
            dedup_key="unreachable",
        )

    appeared_blocking = _blocking(changes.appeared) if changes else ()

    if appeared_blocking:
        titles = ", ".join(issue.title for issue in appeared_blocking[:3])
        return Alert(
            kind=NotificationKind.SITE_BROKEN,
            level=NotificationLevel.CRITICAL,
            title="На сайте появилось то, что запрещает запуск",
            body=(
                f"{titles}. Раньше этого не было — скорее всего, на сайте что-то "
                "поменяли. Пока не исправлено, платный трафик тратится впустую."
            ),
            # Ключ по составу проблем: та же поломка не создаст второе
            # уведомление, а новая — создаст.
            dedup_key="broken:" + ",".join(sorted(i.key.value for i in appeared_blocking)),
        )

    if score is not None and previous_score is not None:
        drop = previous_score - score
        if drop >= SIGNIFICANT_DROP:
            return Alert(
                kind=NotificationKind.SITE_DEGRADED,
                level=NotificationLevel.WARNING,
                title=f"Оценка сайта упала на {drop} пунктов",
                body=(
                    f"Было {previous_score}, стало {score}. Блокирующих замечаний не "
                    "появилось, но что-то на странице изменилось к худшему. "
                    "Загляните в список замечаний."
                ),
                dedup_key=f"degraded:{previous_score}:{score}",
            )

    return None


async def push(
    db: DbSession,
    alert: Alert,
    *,
    organization_id: uuid.UUID,
    project_id: uuid.UUID | None,
    project_name: str,
) -> Notification | None:
    """Записывает уведомление, если такого ещё нет среди непрочитанных.

    Повтор молча пропускается. Ежедневная проверка находит ту же поломку каждый
    день, и без этой защиты список за неделю превратился бы в семь копий одного
    сообщения — то есть в то, что не читают.
    """
    existing = (
        await db.execute(
            select(Notification)
            .where(Notification.organization_id == organization_id)
            .where(Notification.project_id == project_id)
            .where(Notification.dedup_key == alert.dedup_key)
            .where(Notification.is_read.is_(False))
            .limit(1)
        )
    ).scalar_one_or_none()

    if existing is not None:
        return None

    notification = Notification(
        organization_id=organization_id,
        project_id=project_id,
        project_name=project_name,
        kind=alert.kind,
        level=alert.level,
        title=alert.title,
        body=alert.body,
        dedup_key=alert.dedup_key,
    )
    db.add(notification)
    await db.flush()

    return notification


def _blocking(issues: tuple[Issue, ...]) -> tuple[Issue, ...]:
    return tuple(issue for issue in issues if issue.severity is Severity.CRITICAL)
