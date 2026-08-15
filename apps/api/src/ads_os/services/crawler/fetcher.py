"""Загрузка страниц с ограничениями.

Каждое ограничение здесь закрывает конкретный способ навредить: бесконечные
перенаправления, гигантский ответ, медленный сервер, сжатая бомба. Без них
краулер превращается в способ израсходовать ресурсы воркера одним запросом
(v0.3 §97).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import httpx

from .ssrf import UrlNotAllowedError, resolve_and_validate

logger = logging.getLogger(__name__)

USER_AGENT = "ADS-OS-Crawler/0.1 (+https://ai-helper.pro)"


@dataclass(frozen=True, slots=True)
class CrawlLimits:
    """Пределы одной загрузки."""

    timeout_seconds: float = 20.0
    max_redirects: int = 5
    #: Предел на распакованный ответ. Сжатый ответ может быть в сотни раз
    #: меньше — поэтому считается именно то, что получилось после распаковки.
    max_bytes: int = 5 * 1024 * 1024
    max_pages: int = 50


@dataclass(frozen=True, slots=True)
class FetchedPage:
    """Загруженная страница."""

    url: str
    final_url: str
    status_code: int
    content_type: str
    html: str
    #: Цепочка перенаправлений — нужна для аудита и для объяснения выводов.
    redirects: tuple[str, ...] = field(default_factory=tuple)


class FetchError(Exception):
    """Страницу загрузить не удалось."""

    def __init__(self, url: str, reason: str, *, retryable: bool = True) -> None:
        super().__init__(reason)
        self.url = url
        self.reason = reason
        self.retryable = retryable


async def fetch_page(
    url: str,
    *,
    limits: CrawlLimits | None = None,
    client: httpx.AsyncClient | None = None,
) -> FetchedPage:
    """Загружает страницу, проверяя адрес перед каждым переходом."""
    limits = limits or CrawlLimits()
    owns_client = client is None
    client = client or httpx.AsyncClient(
        follow_redirects=False,
        timeout=limits.timeout_seconds,
        headers={"User-Agent": USER_AGENT},
    )

    redirects: list[str] = []
    current = url

    try:
        for _ in range(limits.max_redirects + 1):
            # Проверка повторяется на каждом шаге: публичный адрес может увести
            # редиректом на внутренний, и одной проверки в начале мало.
            resolve_and_validate(current)

            try:
                response = await client.get(current)
            except httpx.TimeoutException as exc:
                raise FetchError(current, "сервер не ответил вовремя") from exc
            except httpx.HTTPError as exc:
                raise FetchError(current, f"ошибка сети: {type(exc).__name__}") from exc

            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    raise FetchError(current, "перенаправление без адреса", retryable=False)
                redirects.append(current)
                current = str(httpx.URL(current).join(location))
                continue

            content_type = response.headers.get("content-type", "").split(";")[0].strip()
            if content_type and not content_type.startswith("text/html"):
                raise FetchError(current, f"ожидался HTML, получен {content_type}", retryable=False)

            body = response.content
            if len(body) > limits.max_bytes:
                # Ответ уже распакован клиентом, поэтому сжатая бомба
                # обнаруживается именно здесь, а не по заголовку длины.
                raise FetchError(
                    current,
                    f"страница больше допустимых {limits.max_bytes} байт",
                    retryable=False,
                )

            return FetchedPage(
                url=url,
                final_url=current,
                status_code=response.status_code,
                content_type=content_type or "text/html",
                html=response.text,
                redirects=tuple(redirects),
            )

        raise FetchError(url, f"больше {limits.max_redirects} перенаправлений", retryable=False)

    except UrlNotAllowedError as exc:
        logger.warning(
            "краулер отклонил адрес",
            extra={"url": exc.url, "reason": exc.reason},
        )
        raise FetchError(exc.url, exc.reason, retryable=False) from exc
    finally:
        if owns_client:
            await client.aclose()
