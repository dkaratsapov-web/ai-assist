"""Учёт квоты Вордстата.

Сто запросов в час на весь сервис — не на проект и не на пользователя. Это
главное ограничение сбора частотностей, и жить с ним приходится всем сразу:
два специалиста, одновременно запустившие сбор, делят одну и ту же сотню.

Отсюда счётчик общий и лежит в Redis, а не в памяти процесса. Воркеров может
быть несколько, и у каждого своя память: три воркера со своим счётчиком по сто
запросов дают триста запросов в час и блокировку в ответ.

**Окно фиксированное, по часам.** Не скользящее: скользящее требует хранить
время каждого запроса и опрашивать этот список на каждом шаге. Разница
проявляется только на стыке часов, а цена — заметно более сложный код в месте,
которое обязано быть надёжным.

**Предел взят с запасом.** Мы считаем свои запросы, площадка — свои, и границы
часа у нас с ней не совпадают. Упереться в её отказ вместо своего предела
означало бы получить 429 на середине сбора; запас в десяток запросов делает
такое маловероятным и заодно оставляет место для ручной проверки ключа.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Protocol

logger = logging.getLogger(__name__)

#: Предел площадки — сто запросов в час. Здесь он с запасом: см. заголовок.
SAFE_PER_HOUR = 90

#: Пауза между запросами. Площадка допускает десять в секунду, но спешить
#: некуда: сбор идёт фоном, а ровный ритм не даёт случайно упереться во второй,
#: посекундный предел.
PAUSE_SECONDS = 0.5

#: Сколько живёт счётчик. Дольше часа, чтобы пережить перевод часов и мелкие
#: расхождения времени, но не бесконечно — иначе в Redis копятся мёртвые ключи.
TTL_SECONDS = 7200


def _window(moment: datetime | None = None) -> str:
    """Имя текущего часа. По нему и считаем."""
    now = moment or datetime.now(UTC)
    return now.strftime("%Y%m%d%H")


def seconds_until_reset(moment: datetime | None = None) -> int:
    """Сколько ждать до обновления лимита.

    Нужно не только планировщику, но и человеку: «продолжим через 40 минут»
    — это ответ, а «квота исчерпана» — нет.
    """
    now = moment or datetime.now(UTC)
    return 3600 - (now.minute * 60 + now.second)


class Quota(Protocol):
    """Кто разрешает сделать запрос."""

    async def take(self) -> bool: ...

    async def remaining(self) -> int: ...


class MemoryQuota:
    """Счётчик в памяти процесса.

    Годится для тестов и для одиночного запуска. В бою не используется: у
    каждого воркера была бы своя сотня.
    """

    def __init__(self, limit: int = SAFE_PER_HOUR) -> None:
        self._limit = limit
        self._window = ""
        self._used = 0

    async def take(self) -> bool:
        window = _window()
        if window != self._window:
            self._window = window
            self._used = 0

        if self._used >= self._limit:
            return False

        self._used += 1
        return True

    async def remaining(self) -> int:
        if _window() != self._window:
            return self._limit
        return max(0, self._limit - self._used)


class RedisQuota:
    """Общий счётчик на все процессы."""

    def __init__(self, url: str, *, limit: int = SAFE_PER_HOUR) -> None:
        self._url = url
        self._limit = limit

    def _key(self) -> str:
        return f"wordstat:quota:{_window()}"

    async def take(self) -> bool:
        """Занимает один запрос из часовой сотни.

        Счётчик увеличивается до проверки, а не после. Обратный порядок — это
        гонка: два воркера прочитали бы «занято 89» и оба сочли бы, что можно.
        """
        import redis.asyncio as redis

        client = redis.from_url(self._url)
        try:
            key = self._key()
            used = int(await client.incr(key))
            if used == 1:
                # Срок жизни ставится только на первом запросе часа: иначе он
                # продлевался бы на каждом, и ключ жил бы вечно.
                await client.expire(key, TTL_SECONDS)
            return used <= self._limit
        except Exception as error:
            # Redis недоступен — сбор останавливается, а не идёт вслепую.
            # Запросы без учёта закончились бы отказом площадки, и разбираться
            # пришлось бы уже с заблокированным доступом.
            logger.warning("счётчик квоты недоступен", extra={"error": type(error).__name__})
            return False
        finally:
            await client.aclose()

    async def remaining(self) -> int:
        import redis.asyncio as redis

        client = redis.from_url(self._url)
        try:
            raw = await client.get(self._key())
            used = int(raw) if raw is not None else 0
            return max(0, self._limit - used)
        except Exception:
            return 0
        finally:
            await client.aclose()


def get_quota(url: str | None = None) -> Quota:
    """Счётчик по настройкам."""
    from ..config import get_settings

    return RedisQuota(url or get_settings().redis_url)
