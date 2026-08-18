"""Отрисовка страниц, которые собираются скриптами.

Обычная загрузка возвращает то, что отдал сервер. У части сайтов это пустой
каркас: содержимое собирает браузер, выполняя скрипты. Наш разбор такой
страницы видит ноль текста, ноль услуг и ноль контактов — и честно говорит, что
не нашёл ничего. Формально верно, практически бесполезно: страница-то у
посетителя показывается полностью.

Здесь эта страница открывается настоящим браузером и отдаётся дальше уже
собранной. Остальной разбор — аудит, анкета клиента, условия конкурентов,
тексты объявлений — не меняется вовсе: ему приходит тот же HTML, просто
непустой.

Почему браузер, а не распознавание картинки. Скриншот требует того же самого
браузера, и после него содержимое пришлось бы угадывать по изображению.
Готовая разметка точнее, дешевле и повторяема: одна и та же страница всегда
даёт один результат.

Цена решения. Браузер занимает сотни мегабайт и секунды на страницу, поэтому
запускается не всегда, а только когда обычный разбор увидел пустой каркас, и
строго по одной странице за раз. На сервере с четырьмя гигабайтами два
одновременных браузера — это отказ всего остального.

Про безопасность. Внутри контейнера у Chromium отключена собственная песочница:
без неё он в контейнере не запускается, а включить её — значит выдать
контейнеру дополнительные привилегии. Границей служит сам контейнер: у воркера
краулера нет доступа к базе, он живёт в отдельной сети и работает не от root.
Адрес перед открытием проходит ту же проверку, что и обычная загрузка.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from typing import Any

from .ssrf import UrlNotAllowedError, resolve_and_validate

logger = logging.getLogger(__name__)

#: Сколько ждём загрузку страницы целиком.
TIMEOUT_SECONDS = 20.0

#: Сколько даём скриптам на дорисовку после того, как сеть затихла. Многие
#: сборки рисуют содержимое в следующем кадре после последнего запроса.
SETTLE_MS = 1200

#: Что не загружаем. Нам нужна разметка, а не внешний вид: картинки и шрифты
#: составляют почти весь вес страницы и на текст не влияют.
BLOCKED_RESOURCES = frozenset({"image", "media", "font"})

#: Предел на размер полученной разметки. Тот же, что у обычной загрузки: разбор
#: дальше по цепочке рассчитан на такие объёмы.
MAX_BYTES = 5 * 1024 * 1024

#: Флаги запуска. Каждый закрывает конкретную проблему контейнера, а не
#:«ускоряет вообще».
_LAUNCH_ARGS = (
    # Своя песочница Chromium в контейнере не поднимается без дополнительных
    # привилегий. Границей служит контейнер целиком — см. заголовок модуля.
    "--no-sandbox",
    # По умолчанию Chromium держит разделяемую память в /dev/shm, а в докере
    # это 64 МБ. Вкладка падает на середине отрисовки, и падение выглядит как
    # «сайт не отвечает».
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--disable-extensions",
    # Фоновые задачи невидимой вкладки нам не нужны, а память едят.
    "--disable-background-timer-throttling",
    "--mute-audio",
)

#: Один браузер за раз на весь процесс. Воркер может взять две задачи
#: одновременно, и два Chromium на этом сервере означают отказ всего
#: остального, включая базу.
_lock = asyncio.Lock()


def is_available() -> bool:
    """Есть ли чем отрисовывать.

    Проверяются обе половины. Playwright ставится только в образ краулера:
    тянуть браузер в образ API, воркера и миграций — это сотни лишних
    мегабайт в каждом. И отдельно проверяется сам браузер по указанному
    пути: библиотека без браузера — состояние вполне возможное, и лучше
    сказать «нечем отрисовать» в лог, чем поймать исключение из чужого кода.
    """
    try:
        import playwright.async_api  # noqa: F401
    except ImportError:
        return False

    chromium = os.environ.get("ADS_OS_CHROMIUM")
    if chromium and not os.path.exists(chromium):
        logger.warning("браузер не найден по указанному пути", extra={"path": chromium})
        return False

    return True


async def render(url: str) -> str | None:
    """Открывает страницу браузером и возвращает собранную разметку.

    Возвращает None, когда отрисовать не удалось: браузера нет, страница не
    открылась, вышло время. Это не ошибка — вызывающий продолжит работать с
    тем, что отдал сервер. Уронить проверку сайта из-за неудачной отрисовки
    значило бы сделать хуже, чем было до неё.
    """
    if not is_available():
        logger.info("отрисовка недоступна: браузер не установлен")
        return None

    try:
        resolve_and_validate(url)
    except UrlNotAllowedError as error:
        logger.warning("отрисовка отклонена", extra={"reason": error.reason})
        return None

    async with _lock:
        try:
            return await asyncio.wait_for(_render(url), timeout=TIMEOUT_SECONDS + 10)
        except TimeoutError:
            logger.warning("отрисовка не уложилась во время", extra={"url": url[:200]})
            return None
        except Exception as error:
            # Браузер падает по десятку причин, зависящих от чужой страницы.
            # Ни одна из них не должна отменять проверку сайта целиком.
            logger.warning(
                "отрисовка не удалась",
                extra={"url": url[:200], "error": type(error).__name__},
            )
            return None


async def _render(url: str) -> str | None:
    from playwright.async_api import async_playwright

    async with async_playwright() as driver:
        # Путь к браузеру берётся из окружения: в образе краулера стоит
        # системный Chromium, а собственную сборку Playwright скачивать
        # запрещено — в интернет этому воркеру можно только к проверяемым
        # сайтам.
        browser = await driver.chromium.launch(
            args=list(_LAUNCH_ARGS),
            executable_path=os.environ.get("ADS_OS_CHROMIUM") or None,
        )
        try:
            page = await browser.new_page()
            await page.route("**/*", _skip_heavy)

            await page.goto(url, timeout=TIMEOUT_SECONDS * 1000, wait_until="domcontentloaded")
            # Ждём затишья в сети, но не считаем его обязательным: на сайтах с
            # постоянными запросами — чатами, аналитикой, опросами — оно не
            # наступает никогда, а содержимое давно на месте.
            with contextlib.suppress(Exception):
                await page.wait_for_load_state("networkidle", timeout=5000)
            await page.wait_for_timeout(SETTLE_MS)

            html = str(await page.content())
        finally:
            await browser.close()

    if len(html.encode()) > MAX_BYTES:
        logger.warning("отрисованная страница слишком велика", extra={"url": url[:200]})
        return None

    return html


async def _skip_heavy(route: Any, request: Any) -> None:
    if request.resource_type in BLOCKED_RESOURCES:
        await route.abort()
    else:
        await route.continue_()
