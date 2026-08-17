"""Разметка ссылок.

Главное, что проверяется: разметка ничего не ломает. Она добавляется к чужим
адресам, где уже могут висеть свои параметры, и попадает в файл, который
человек грузит в Коммандер. Ошибка здесь стоит месяца отчётов, по которым
нельзя ничего решить.
"""

from __future__ import annotations

from ads_os.services.utm import (
    CAMPAIGN_ID,
    GROUP_ID,
    KEYWORD,
    NOTES,
    UtmTemplate,
    preview,
    slug,
    tag,
)

TEMPLATE = UtmTemplate()


def params(url: str) -> dict[str, str]:
    query = url.split("?", 1)[1] if "?" in url else ""
    return dict(item.split("=", 1) for item in query.split("&") if item)


class TestРазметка:
    def test_основные_метки_проставляются(self) -> None:
        result = params(tag("https://example.com/", TEMPLATE))

        assert result["utm_source"] == "yandex"
        assert result["utm_medium"] == "cpc"

    def test_подстановки_директа_не_кодируются(self) -> None:
        """Закодированные скобки площадка не распознает, и в отчёт уедет
        буквальное «%7Bkeyword%7D» вместо фразы."""
        result = tag("https://example.com/", TEMPLATE)

        assert KEYWORD in result
        assert GROUP_ID in result
        assert "%7B" not in result

    def test_свои_параметры_страницы_сохраняются(self) -> None:
        """На посадочных висят метки партнёров и варианты страницы. Потерять их
        значит сломать чужой учёт."""
        result = params(tag("https://example.com/?partner=abc&v=2", TEMPLATE))

        assert result["partner"] == "abc"
        assert result["v"] == "2"
        assert result["utm_source"] == "yandex"

    def test_заданные_вручную_метки_не_переписываются(self) -> None:
        """Если человек проставил метку сам, у него была причина."""
        result = params(tag("https://example.com/?utm_source=vk", TEMPLATE))

        assert result["utm_source"] == "vk"

    def test_якорь_остаётся_в_конце(self) -> None:
        """Иначе ссылка перестаёт открывать нужный раздел страницы."""
        assert tag("https://example.com/page#form", TEMPLATE).endswith("#form")

    def test_название_кампании_подставляется(self) -> None:
        result = params(tag("https://example.com/", TEMPLATE, campaign_name="okna_tver"))

        assert result["utm_campaign"] == "okna_tver"

    def test_без_названия_берётся_номер_кампании(self) -> None:
        """Имя, введённое руками, рано или поздно разойдётся с настоящим."""
        assert CAMPAIGN_ID in tag("https://example.com/", TEMPLATE)

    def test_пустой_адрес_не_ломает(self) -> None:
        assert tag("", TEMPLATE) == ""

    def test_повторная_разметка_не_удваивает_метки(self) -> None:
        once = tag("https://example.com/", TEMPLATE)

        assert tag(once, TEMPLATE) == once


class TestНазвание:
    def test_кириллица_транслитерируется(self) -> None:
        """В отчёте русские буквы превращаются в проценты с цифрами, и читать
        их приходится в конвертере."""
        assert slug("Окна Тверь") == "okna_tver"

    def test_лишние_знаки_убираются(self) -> None:
        assert slug("Окна / Тверь (поиск)") == "okna_tver_poisk"

    def test_длина_ограничена(self) -> None:
        assert len(slug("окно" * 50)) <= 60


class TestПояснения:
    def test_объяснены_фигурные_скобки(self) -> None:
        """Строка со скобками выглядит как ошибка, и это первый вопрос."""
        assert any("скобки" in note for note in NOTES)

    def test_пример_показывает_настоящие_значения(self) -> None:
        result = preview("https://example.com/", TEMPLATE)

        assert "{" not in result
        assert "12345678" in result
