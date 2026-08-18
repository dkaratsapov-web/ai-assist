"""Кто это на самом деле: конкурент, площадка или статья.

Смысл проверок здесь один: у Авито всегда есть форма, цены и отзывы, и из
того, что у клиента их нет, не следует ничего. Поэтому площадка должна
опознаваться, а сравнение с ней — помечаться как бессмысленное.
"""

from __future__ import annotations

from ads_os.services.ai import (
    AiProviderError,
    AiResult,
    AiUsage,
    ProviderRegistry,
    StubProvider,
)
from ads_os.services.rival_kind import (
    KIND_HINTS,
    KIND_LABELS,
    Kind,
    KindVerdict,
    Source,
    classify,
    domain,
    known,
)

TEXT = (
    "Натяжные потолки под ключ в Твери. Монтаж от 350 рублей за метр, "
    "замер бесплатно, гарантия 10 лет. Работаем с 2010 года. " * 6
)


class Model:
    name = "openai"

    def __init__(self, answer: object) -> None:
        self.answer = answer
        self.calls = 0

    async def complete(self, request: object) -> object:
        self.calls += 1
        if isinstance(self.answer, Exception):
            raise self.answer
        return AiResult(
            payload=self.answer,
            confidence=0.8,
            reasoning_summary="",
            usage=AiUsage(provider="openai", model="модель-1", output_tokens=20),
        )


def registry(provider: object) -> ProviderRegistry:
    return ProviderRegistry(default=provider)  # type: ignore[arg-type]


def verdict(kind: Kind, *, sells: bool = True) -> KindVerdict:
    return KindVerdict(kind=kind, reason="Заявка уходит владельцу сайта.", sells_directly=sells)


class TestИзвестныеПлощадки:
    async def test_площадка_узнаётся_по_адресу(self) -> None:
        """Авито остаётся Авито, что бы ни было на странице."""
        result = await classify("https://www.avito.ru/tver/remont", TEXT)

        assert result.kind is Kind.AGGREGATOR
        assert result.source is Source.KNOWN

    async def test_известный_домен_модели_не_отправляется(self) -> None:
        """Платить за то, что и так точно известно, незачем."""
        model = Model(verdict(Kind.COMPETITOR))

        await classify("https://2gis.ru/tver/firm/1", TEXT, registry=registry(model))

        assert model.calls == 0

    def test_поддомен_считается_той_же_площадкой(self) -> None:
        assert known("https://msk.avito.ru/") is Kind.AGGREGATOR

    def test_услуги_не_путаются_с_яндексом_вообще(self) -> None:
        """Проверка идёт от полного имени к короткому — иначе поддомен
        опознавался бы по хвосту и терял свою суть."""
        assert known("https://uslugi.yandex.ru/tver") is Kind.AGGREGATOR

    def test_обычный_сайт_не_числится_известным(self) -> None:
        assert known("https://potolki-tver.ru/") is None

    def test_домен_чистится_от_лишнего(self) -> None:
        assert domain("https://WWW.Example.RU:443/path?a=1") == "example.ru"


class TestРазборМоделью:
    async def test_незнакомый_сайт_разбирает_модель(self) -> None:
        result = await classify(
            "https://potolki-tver.ru/", TEXT, registry=registry(Model(verdict(Kind.COMPETITOR)))
        )

        assert result.kind is Kind.COMPETITOR
        assert result.source is Source.MODEL

    async def test_конкурент_без_прямой_продажи_считается_площадкой(self) -> None:
        """Ответ «конкурент» с чужими исполнителями противоречит сам себе.
        Верим признаку, а не ярлыку: по нему и проходит настоящая граница."""
        result = await classify(
            "https://masters-tver.ru/",
            TEXT,
            registry=registry(Model(verdict(Kind.COMPETITOR, sells=False))),
        )

        assert result.kind is Kind.AGGREGATOR

    async def test_потребление_возвращается_для_учёта(self) -> None:
        result = await classify(
            "https://potolki-tver.ru/", TEXT, registry=registry(Model(verdict(Kind.ARTICLE)))
        )

        assert result.tokens == 20


class TestСравнимость:
    async def test_с_площадкой_сравниваться_бессмысленно(self) -> None:
        """У неё всегда есть форма, цены и отзывы."""
        result = await classify("https://avito.ru/tver", TEXT)

        assert result.comparable is False
        assert result.as_stored()["hint"]

    async def test_с_конкурентом_сравниваться_можно(self) -> None:
        result = await classify(
            "https://potolki-tver.ru/", TEXT, registry=registry(Model(verdict(Kind.COMPETITOR)))
        )

        assert result.comparable is True

    def test_у_каждого_вида_есть_название_и_объяснение(self) -> None:
        """Ярлык без объяснения человек не может ни принять, ни оспорить."""
        for kind in Kind:
            assert KIND_LABELS[kind]
            assert KIND_HINTS[kind]


class TestБезотказность:
    async def test_сбой_модели_не_ломает_разбор_конкурента(self) -> None:
        result = await classify(
            "https://potolki-tver.ru/",
            TEXT,
            registry=registry(Model(AiProviderError("модель недоступна"))),
        )

        assert result.kind is Kind.OTHER
        assert result.reason

    async def test_заглушка_не_вешает_ярлык(self) -> None:
        """Пометить конкурента площадкой по выдумке заглушки — испортить
        сравнение молча."""
        model = StubProvider()
        result = await classify("https://potolki-tver.ru/", TEXT, registry=registry(model))

        assert result.source is Source.UNKNOWN
        assert "не подключено" in result.reason

    async def test_пустая_страница_модели_не_отправляется(self) -> None:
        model = Model(verdict(Kind.COMPETITOR))
        result = await classify("https://potolki-tver.ru/", "коротко", registry=registry(model))

        assert model.calls == 0
        assert result.kind is Kind.OTHER
