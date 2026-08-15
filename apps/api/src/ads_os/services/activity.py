"""Запись действий в журнал.

Один вызов на действие, из обработчика. Осознанно без магии: перехватчик
записывал бы всё подряд и требовал бы догадываться, что именно произошло, — а
формулировка «изменил проект» без указания, что изменилось, бесполезна.

Модуль не бросает исключений наружу. Журнал важен, но не важнее самого
действия: если запись почему-то не удалась, пользователь всё равно должен
получить результат своей работы, а не ошибку.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..models.activity import ActivityAction, ActivityLog
from ..tenancy.context import TenantContext

logger = logging.getLogger(__name__)

#: Что показывать в ленте для каждого действия. Формулировки в прошедшем
#: времени и от третьего лица: строка читается как «Иван Петров создал проект».
ACTION_LABELS: dict[ActivityAction, str] = {
    ActivityAction.PROJECT_CREATED: "создал проект",
    ActivityAction.PROJECT_UPDATED: "изменил проект",
    ActivityAction.PROJECT_DELETED: "удалил проект",
    ActivityAction.ECONOMICS_UPDATED: "изменил экономику проекта",
    ActivityAction.AUDIT_STARTED: "запустил проверку сайта",
    ActivityAction.COMPETITOR_ADDED: "добавил конкурента",
    ActivityAction.COMPETITOR_REMOVED: "удалил конкурента",
    ActivityAction.MEMBER_ADDED: "добавил участника",
    ActivityAction.MEMBER_UPDATED: "изменил участника",
}

#: Поля, значения которых в журнал не попадают никогда.
#:
#: Журнал читают люди, и он живёт дольше всего остального. Секрету достаточно
#: попасть в него один раз, чтобы остаться там навсегда.
SENSITIVE_KEYS = frozenset({"token", "secret", "password", "client_secret"})

#: Длинные значения обрезаются: журнал — это лента коротких строк, а не место
#: для хранения содержимого полей.
MAX_VALUE_LENGTH = 120


def _clean(details: dict[str, Any] | None) -> dict[str, Any]:
    if not details:
        return {}

    cleaned: dict[str, Any] = {}
    for key, value in details.items():
        if any(marker in key.lower() for marker in SENSITIVE_KEYS):
            continue
        text = "" if value is None else str(value)
        cleaned[key] = text[:MAX_VALUE_LENGTH] if len(text) > MAX_VALUE_LENGTH else text

    return cleaned


async def record(
    session: AsyncSession,
    ctx: TenantContext,
    action: ActivityAction,
    *,
    subject: str,
    actor_name: str,
    project_id: uuid.UUID | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Записывает действие. Никогда не мешает основному действию."""
    try:
        session.add(
            ActivityLog(
                organization_id=ctx.organization_id,
                user_id=ctx.user_id,
                user_name=actor_name[:200],
                action=action,
                project_id=project_id,
                subject=subject[:300],
                details=_clean(details),
            )
        )
        await session.flush()
    except Exception:
        # Действие уже выполнено; ронять запрос из-за журнала нельзя.
        logger.exception(
            "не удалось записать действие в журнал",
            extra={"action": action.value},
        )


def changed_fields(before: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    """Собирает пары «было → стало» только по действительно изменившимся полям.

    Записывать поля, которые прислали, но не поменяли, — верный способ сделать
    журнал нечитаемым: каждое сохранение формы выглядело бы как правка всего
    сразу.
    """
    changes: dict[str, Any] = {}

    for key, new_value in updates.items():
        old_value = before.get(key)
        if str(old_value) == str(new_value):
            continue
        changes[key] = f"{_show(old_value)} → {_show(new_value)}"

    return changes


def _show(value: Any) -> str:
    if value is None or value == "":
        return "пусто"
    return str(value)
