"""Приведение почты к одному виду.

Доступ выдают по одному написанию адреса, а входят с другим. Каждый случай
здесь — это человек, которому уже выдали доступ и который получил бы отказ.
"""

from __future__ import annotations

import pytest

from ads_os.services.yandex_email import looks_like_email, normalize, same_person


class TestДоменыСинонимы:
    @pytest.mark.parametrize(
        "address",
        ["ivan@ya.ru", "ivan@yandex.com", "ivan@yandex.by", "ivan@yandex.kz", "IVAN@Yandex.RU"],
    )
    def test_все_домены_яндекса_ведут_в_один_ящик(self, address: str) -> None:
        assert normalize(address) == "ivan@yandex.ru"

    def test_чужой_домен_не_трогается(self) -> None:
        """Правила Яндекса верны для Яндекса. Перенести их на gmail значит
        счесть два разных ящика одним."""
        assert normalize("ivan.petrov@gmail.com") == "ivan.petrov@gmail.com"


class TestЛогин:
    def test_точка_и_дефис_равнозначны(self) -> None:
        """Владелец пишет с точкой — как в визитке. Яндекс присылает с дефисом."""
        assert same_person("ivan.petrov@ya.ru", "ivan-petrov@yandex.ru") is True

    def test_без_разделителя_это_другой_человек(self) -> None:
        """«ivanpetrov» и «ivan.petrov» — разные логины, склеивать нельзя."""
        assert same_person("ivanpetrov@ya.ru", "ivan.petrov@ya.ru") is False

    def test_пробелы_по_краям_не_мешают(self) -> None:
        assert same_person("  Ivan@Ya.RU ", "ivan@yandex.ru") is True

    def test_разные_люди_остаются_разными(self) -> None:
        assert same_person("ivan@yandex.ru", "petr@yandex.ru") is False


class TestПохожеНаПочту:
    @pytest.mark.parametrize("value", ["ivan@yandex.ru", "a.b+c@example.co.uk"])
    def test_адрес_принимается(self, value: str) -> None:
        assert looks_like_email(value) is True

    @pytest.mark.parametrize("value", ["", "ivan", "ivan@yandex", "ivan @yandex.ru", "@yandex.ru"])
    def test_не_адрес_отклоняется(self, value: str) -> None:
        assert looks_like_email(value) is False

    def test_проверка_нарочно_грубая(self) -> None:
        """Строгая проверка по стандарту отвергает существующие рабочие ящики,
        а настоящую пригодность адреса покажет только вход."""
        assert looks_like_email("очень.странный_адрес@почта.рф") is True
