"""Сравнение с конкурентами (v0.3 §16)."""

from __future__ import annotations

from ads_os.services.audit import collect_signals
from ads_os.services.competitors import (
    FeatureKey,
    Participant,
    compare,
    extract_features,
)

WITH_EVERYTHING = """
<html><head><title>Ремонт</title><meta name="viewport" content="width=device-width">
<script>ym(12345678,'init',{});</script></head>
<body><h1>Ремонт за 1 час</h1><p>от 3 500 ₽, гарантия 12 месяцев, отзывы клиентов</p>
<form><input name="phone"><button>Оставить заявку</button></form>
<p>+7 (900) 123-45-67</p><a href="https://t.me/example">Telegram</a></body></html>
"""

BARE = "<html><head><title>Пусто</title></head><body><h1>Компания</h1></body></html>"


def participant(url: str, html: str, title: str = "") -> Participant:
    features = extract_features(collect_signals(html))
    return Participant(url=url, title=title or url, features=features)


class TestПризнаки:
    def test_наполненная_страница_даёт_все_признаки(self) -> None:
        features = extract_features(collect_signals(WITH_EVERYTHING))
        assert all(features.values())

    def test_пустая_страница_не_даёт_ни_одного(self) -> None:
        features = extract_features(collect_signals(BARE))
        assert not any(features.values())

    def test_признаки_берутся_тем_же_разбором_что_и_аудит(self) -> None:
        """Разные правила для своего и чужого сайта обесценили бы сравнение."""
        signals = collect_signals(WITH_EVERYTHING)
        features = extract_features(signals)
        assert features[FeatureKey.ANALYTICS] is signals.has_analytics
        assert features[FeatureKey.FORM] == (signals.forms > 0)


class TestСравнение:
    def test_без_конкурентов_вывода_нет(self) -> None:
        """Сравнивать не с чем — значит и говорить нечего."""
        result = compare(participant("https://mine.ru/", BARE), ())
        assert result.summary is None
        assert result.gaps == ()

    def test_все_строки_присутствуют(self) -> None:
        result = compare(participant("https://mine.ru/", BARE), ())
        assert len(result.rows) == len(FeatureKey)

    def test_пробел_это_то_чего_нет_у_нас_но_есть_у_большинства(self) -> None:
        result = compare(
            participant("https://mine.ru/", BARE),
            (
                participant("https://a.ru/", WITH_EVERYTHING),
                participant("https://b.ru/", WITH_EVERYTHING),
            ),
        )
        keys = {row.key for row in result.gaps}
        assert FeatureKey.FORM in keys
        assert FeatureKey.PRICES in keys

    def test_единственный_конкурент_с_признаком_не_делает_его_пробелом(self) -> None:
        """Один конкурент с необычным решением — это разница подходов."""
        result = compare(
            participant("https://mine.ru/", BARE),
            (
                participant("https://a.ru/", WITH_EVERYTHING),
                participant("https://b.ru/", BARE),
                participant("https://c.ru/", BARE),
            ),
        )
        assert result.gaps == ()

    def test_преимущество_это_то_что_есть_только_у_нас(self) -> None:
        result = compare(
            participant("https://mine.ru/", WITH_EVERYTHING),
            (participant("https://a.ru/", BARE), participant("https://b.ru/", BARE)),
        )
        assert len(result.advantages) == len(FeatureKey)
        assert result.gaps == ()

    def test_вывод_называет_конкретные_признаки(self) -> None:
        """«Есть отставание» без перечисления не говорит, что делать."""
        result = compare(
            participant("https://mine.ru/", BARE),
            (participant("https://a.ru/", WITH_EVERYTHING),),
        )
        assert result.summary is not None
        assert "форма заявки" in result.summary

    def test_равенство_описывается_как_равенство(self) -> None:
        result = compare(
            participant("https://mine.ru/", WITH_EVERYTHING),
            (participant("https://a.ru/", WITH_EVERYTHING),),
        )
        assert result.gaps == ()
        assert result.summary is not None
        assert "не уступаете" in result.summary

    def test_у_каждой_строки_есть_объяснение_зачем(self) -> None:
        """Признак без последствий для рекламы в таблице не нужен."""
        result = compare(participant("https://mine.ru/", BARE), ())
        assert all(row.why for row in result.rows)
