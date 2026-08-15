"""Защита краулера — SEC-007, SEC-008, SEC-009 из плана безопасности.

Краулер принимает адрес от пользователя и ходит по сети сам. Если он сможет
обратиться внутрь периметра, злоумышленнику не нужно ничего взламывать: он
просто попросит систему сходить по нужному адресу и показать ответ.
"""

from __future__ import annotations

import socket

import httpx
import pytest

from ads_os.services.crawler.fetcher import CrawlLimits, FetchError, fetch_page
from ads_os.services.crawler.ssrf import (
    UrlNotAllowedError,
    is_blocked_address,
    resolve_and_validate,
)


def resolver_for(*addresses: str):
    """Подменяет разрешение имён: тесты не должны зависеть от внешнего DNS."""

    def _resolve(host: str, port: int, **kwargs: object):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (a, port))
            for a in addresses
        ]

    return _resolve


class TestSEC007Петля:
    @pytest.mark.parametrize(
        "url",
        [
            "http://127.0.0.1/",
            "http://127.0.0.1:8000/api/v1/health",
            "http://localhost/",
            "http://[::1]/",
            "http://127.1/",
        ],
    )
    def test_обращение_к_себе_запрещено(self, url: str) -> None:
        with pytest.raises(UrlNotAllowedError):
            resolve_and_validate(url, resolver=resolver_for("127.0.0.1"))


class TestSEC008ПриватныеСети:
    @pytest.mark.parametrize(
        "address",
        ["10.0.0.5", "172.16.31.7", "192.168.1.1", "100.64.0.1", "fd00::1", "fe80::1"],
    )
    def test_приватные_адреса_запрещены(self, address: str) -> None:
        assert is_blocked_address(address) is True

    def test_имя_указывающее_внутрь_запрещено(self) -> None:
        """Имя может быть публичным, а адрес за ним — внутренним."""
        with pytest.raises(UrlNotAllowedError, match="внутреннем диапазоне"):
            resolve_and_validate("https://internal.example.com/", resolver=resolver_for("10.1.2.3"))

    def test_проверяются_все_адреса_имени(self) -> None:
        """Имя может отдавать публичный и внутренний адрес вперемешку.

        Проверять только первый нельзя: какой из них выберет система при
        подключении, мы не контролируем.
        """
        with pytest.raises(UrlNotAllowedError):
            resolve_and_validate(
                "https://mixed.example.com/", resolver=resolver_for("93.184.216.34", "10.0.0.9")
            )


class TestSEC009Метаданные:
    def test_адрес_метаданных_облака_запрещён(self) -> None:
        """169.254.169.254 отдаёт ключи доступа к облаку."""
        assert is_blocked_address("169.254.169.254") is True

    @pytest.mark.parametrize("host", ["metadata.google.internal", "metadata", "instance-data"])
    def test_имена_сервисов_метаданных_запрещены(self, host: str) -> None:
        with pytest.raises(UrlNotAllowedError, match="запрещено"):
            resolve_and_validate(f"http://{host}/", resolver=resolver_for("93.184.216.34"))


class TestРазрешённое:
    def test_публичный_адрес_проходит(self) -> None:
        target = resolve_and_validate(
            "https://example.com/page", resolver=resolver_for("93.184.216.34")
        )
        assert target.hostname == "example.com"
        assert target.port == 443
        assert target.addresses == ("93.184.216.34",)

    def test_порт_по_умолчанию_зависит_от_схемы(self) -> None:
        target = resolve_and_validate("http://example.com/", resolver=resolver_for("93.184.216.34"))
        assert target.port == 80


class TestСхемыИФорма:
    @pytest.mark.parametrize(
        "url",
        ["file:///etc/passwd", "ftp://example.com/", "gopher://example.com/", "data:text/html,x"],
    )
    def test_чужие_схемы_запрещены(self, url: str) -> None:
        with pytest.raises(UrlNotAllowedError, match="схема"):
            resolve_and_validate(url, resolver=resolver_for("93.184.216.34"))

    def test_учётные_данные_в_адресе_запрещены(self) -> None:
        """Заодно закрывает утечку пароля в логи и историю запросов."""
        with pytest.raises(UrlNotAllowedError, match="учётные данные"):
            resolve_and_validate(
                "https://user:secret@example.com/", resolver=resolver_for("93.184.216.34")
            )

    def test_адрес_без_имени_запрещён(self) -> None:
        with pytest.raises(UrlNotAllowedError, match="имя узла"):
            resolve_and_validate("https:///path", resolver=resolver_for("93.184.216.34"))

    def test_ipv4_завёрнутый_в_ipv6_не_обходит_проверку(self) -> None:
        """Запись ::ffff:127.0.0.1 — тот же localhost другими буквами."""
        assert is_blocked_address("::ffff:127.0.0.1") is True


class TestОграниченияЗагрузки:
    async def test_перенаправление_внутрь_периметра_прерывает_загрузку(self) -> None:
        """Проверка повторяется на каждом шаге, а не только в начале."""

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "example.com":
                return httpx.Response(
                    302, headers={"location": "http://169.254.169.254/latest/meta-data/"}
                )
            return httpx.Response(200, text="<html></html>", headers={"content-type": "text/html"})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)
        with pytest.raises(FetchError, match=r"запрещено|внутреннем диапазоне"):
            await fetch_page("https://example.com/", client=client)
        await client.aclose()

    async def test_слишком_много_перенаправлений(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(302, headers={"location": "https://example.com/next"})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)
        with pytest.raises(FetchError, match="перенаправлений"):
            await fetch_page(
                "https://example.com/", client=client, limits=CrawlLimits(max_redirects=2)
            )
        await client.aclose()

    async def test_слишком_большая_страница_отклоняется(self) -> None:
        """Сжатый ответ бывает в сотни раз меньше распакованного."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                text="<html>" + "a" * 5000 + "</html>",
                headers={"content-type": "text/html; charset=utf-8"},
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)
        with pytest.raises(FetchError, match="больше допустимых"):
            await fetch_page(
                "https://example.com/", client=client, limits=CrawlLimits(max_bytes=1000)
            )
        await client.aclose()

    async def test_не_html_отклоняется(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, content=b"%PDF-1.4", headers={"content-type": "application/pdf"}
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)
        with pytest.raises(FetchError, match="ожидался HTML"):
            await fetch_page("https://example.com/", client=client)
        await client.aclose()

    async def test_успешная_загрузка_сохраняет_цепочку_перенаправлений(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/":
                return httpx.Response(301, headers={"location": "https://example.com/final"})
            return httpx.Response(
                200,
                text="<html><body>Привет</body></html>",
                headers={"content-type": "text/html; charset=utf-8"},
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)
        page = await fetch_page("https://example.com/", client=client)
        await client.aclose()

        assert page.status_code == 200
        assert page.final_url == "https://example.com/final"
        assert page.redirects == ("https://example.com/",)
        assert "Привет" in page.html
