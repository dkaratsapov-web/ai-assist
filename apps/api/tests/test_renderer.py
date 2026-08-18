"""Отрисовка страниц, собираемых скриптами.

Проверяется прежде всего безотказность. Отрисовка — это дополнение к обычной
загрузке, а не замена ей: любая её неудача должна оставлять проверку сайта
работать на том, что отдал сервер. Отрисовка, которая роняет аудит, хуже
отсутствующей.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest

from ads_os.services.audit import collect_signals, looks_js_rendered
from ads_os.services.crawler import renderer

#: Пустой каркас: ровно то, что отдаёт сервер у сайтов на скриптах.
SHELL = (
    "<html><head><title>Айпапа</title></head><body><div id='root'></div>"
    "<script>var a=1</script><script>var b=2</script><script>var c=3</script>"
    "</body></html>"
)


class TestКогдаВключается:
    def test_пустой_каркас_опознаётся(self) -> None:
        """Это и есть переключатель: браузер запускается только здесь."""
        assert looks_js_rendered(collect_signals(SHELL)) is True

    def test_обычная_страница_браузера_не_требует(self) -> None:
        """Иначе браузер запускался бы на каждом сайте — это секунды и сотни
        мегабайт там, где всё и так прочитано."""
        html = (
            "<html><body><h1>Натяжные потолки в Твери</h1>"
            "<p>" + "Монтаж от 350 рублей за метр. Замер бесплатно. " * 20 + "</p>"
            "</body></html>"
        )

        assert looks_js_rendered(collect_signals(html)) is False


class TestБезотказность:
    async def test_без_браузера_возвращается_пусто(self) -> None:
        """В образе API браузера нет, и это не ошибка."""
        with patch.object(renderer, "is_available", return_value=False):
            assert await renderer.render("https://example.com/") is None

    async def test_запрещённый_адрес_не_открывается(self) -> None:
        """Браузер сам резолвит имена и ходит по редиректам мимо нашей проверки,
        поэтому адрес проверяется до его запуска."""
        with patch.object(renderer, "is_available", return_value=True):
            assert await renderer.render("http://127.0.0.1/admin") is None

    async def test_падение_браузера_не_роняет_проверку(self) -> None:
        with (
            patch.object(renderer, "is_available", return_value=True),
            patch.object(renderer, "_render", AsyncMock(side_effect=RuntimeError("упал"))),
        ):
            assert await renderer.render("https://example.com/") is None

    async def test_превышение_времени_возвращает_пусто(self) -> None:
        with (
            patch.object(renderer, "is_available", return_value=True),
            patch.object(renderer, "_render", AsyncMock(side_effect=TimeoutError)),
        ):
            assert await renderer.render("https://example.com/") is None


class TestНастоящийБраузер:
    """Прогон на живом Chromium.

    Пропускается там, где браузера нет: в образе API его и не должно быть.
    """

    async def test_страница_на_скриптах_дорисовывается(self) -> None:
        # Одной библиотеки мало: без самого браузера отрисовывать нечем, и
        # такой прогон проверял бы только сообщение об ошибке.
        chromium = os.environ.get("ADS_OS_CHROMIUM")
        if not renderer.is_available() or not chromium or not os.path.exists(chromium):
            pytest.skip("браузер не установлен")

        page = (
            # Кодировка объявляется явно: у data-адреса нет заголовков ответа, и
            # без неё браузер читает байты как латиницу. Настоящие сайты
            # присылают её заголовком, здесь этого сделать негде.
            "<html><head><meta charset='utf-8'></head><body><div id='root'></div><script>"
            "document.getElementById('root').innerHTML = "
            "'<h1>Натяжные потолки в Твери</h1><p>' + "
            "'Монтаж от 350 руб. за метр, замер бесплатно, гарантия 10 лет. '.repeat(10) + "
            "'</p>';"
            "</script></body></html>"
        )
        # data: адрес открывается браузером без сети — проверяем саму отрисовку,
        # а не доступность чужого сайта.
        import base64

        url = "data:text/html;base64," + base64.b64encode(page.encode()).decode()

        html = await renderer._render(url)

        assert html is not None
        assert "Натяжные потолки в Твери" in html
        assert looks_js_rendered(collect_signals(html)) is False
