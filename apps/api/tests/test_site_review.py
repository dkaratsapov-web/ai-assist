"""Разбор посадочной страницы моделью.

Главное здесь — границы. Мнение модели не должно ни ломать проверку сайта, ни
подмешиваться в балл готовности, ни выдавать за разбор выдумку заглушки. И
контакты со страницы не должны уезжать внешнему провайдеру.
"""

from __future__ import annotations

import pathlib

import pytest

from ads_os.services.ai import (
    AiProviderError,
    AiResult,
    AiUsage,
    ProviderRegistry,
    StubProvider,
)
from ads_os.services.audit import collect_signals
from ads_os.services.redact import has_contacts, redact
from ads_os.services.site_review import (
    Grade,
    ReviewNote,
    SiteReview,
    Topic,
    known_facts,
    page_text,
    review_page,
)

PAGE = (
    "<html><head><title>Натяжные потолки в Твери</title></head><body>"
    "<h1>Натяжные потолки под ключ</h1>"
    "<p>Монтаж от 350 рублей за метр. Замер бесплатно. Гарантия 10 лет.</p>"
    "<p>Звоните: +7 (900) 123-45-67 или пишите на info@potolki.ru</p>"
    "<p>" + "Работаем в Твери и области с 2010 года. " * 20 + "</p>"
    "<form><input name='name'><input name='phone'></form>"
    "<script>var tracker = 1;</script>"
    "</body></html>"
)

ANSWER = SiteReview(
    summary="Предложение понятное, но цена без условий.",
    strongest="Гарантия 10 лет вынесена на первый экран.",
    weakest="Не сказано, что входит в цену 350 рублей.",
    notes=[
        ReviewNote(
            topic=Topic.OFFER,
            grade=Grade.WEAK,
            what="Цена указана без состава работ.",
            fix="Показать, что входит в 350 рублей за метр.",
            quote="Монтаж от 350 рублей за метр",
        )
    ],
)


class Model:
    """Провайдер, отвечающий заранее заданным разбором."""

    name = "openai"

    def __init__(self, answer: object = ANSWER) -> None:
        self.answer = answer
        self.seen: list[object] = []

    async def complete(self, request: object) -> object:
        self.seen.append(request)
        if isinstance(self.answer, Exception):
            raise self.answer
        return AiResult(
            payload=self.answer,
            confidence=0.7,
            reasoning_summary="",
            usage=AiUsage(provider="openai", model="модель-1"),
        )


def registry(provider: object) -> ProviderRegistry:
    return ProviderRegistry(default=provider)  # type: ignore[arg-type]


class TestКонтакты:
    def test_телефон_не_уходит_модели(self) -> None:
        assert "+7 (900) 123-45-67" not in page_text(PAGE)
        assert "[телефон]" in page_text(PAGE)

    def test_почта_не_уходит_модели(self) -> None:
        assert "info@potolki.ru" not in page_text(PAGE)

    def test_цена_остаётся(self) -> None:
        """Шаблон телефона узкий намеренно: без цен разбор бессмыслен."""
        assert "1 200 000" in redact("Квартира за 1 200 000 рублей")

    def test_отсутствие_телефона_видно_модели(self) -> None:
        """«Позвоните нам [телефон]» и «Позвоните нам» — разные страницы."""
        assert has_contacts("Тел. 8 900 123 45 67") is True
        assert has_contacts("Просто текст без номеров") is False

    def test_ссылки_на_звонок_тоже_вычищаются(self) -> None:
        assert "89001234567" not in redact("<a href=tel:+79001234567>")


class TestФакты:
    def test_проверенное_кодом_передаётся_модели(self) -> None:
        """Иначе модель пересказывает проверенное и ошибается в этом."""
        facts = known_facts(collect_signals(PAGE))

        assert "Цены на странице: есть" in facts
        assert "Форма заявки: есть" in facts

    def test_скрипты_в_текст_не_попадают(self) -> None:
        assert "var tracker" not in page_text(PAGE)


class TestРазбор:
    async def test_мнение_возвращается(self) -> None:
        result = await review_page(PAGE, collect_signals(PAGE), registry=registry(Model()))

        assert result.ok is True
        assert result.review is not None
        assert result.review.notes[0].quote == "Монтаж от 350 рублей за метр"

    async def test_модель_и_уверенность_сохраняются(self) -> None:
        """Без них человеку нечем оценить, насколько мнению верить."""
        result = await review_page(PAGE, collect_signals(PAGE), registry=registry(Model()))

        assert result.confidence == 0.7
        assert result.model == "модель-1"

    async def test_страница_уходит_помеченной_как_данные(self) -> None:
        model = Model()
        await review_page(
            PAGE, collect_signals(PAGE), registry=registry(model), url="https://a.ru/"
        )

        request = model.seen[0]
        assert request.content[0].source == "https://a.ru/"  # type: ignore[attr-defined]

    async def test_замечания_обрезаются_по_числу(self) -> None:
        """Список из тридцати пунктов человек не читает, а закрывает."""
        many = SiteReview(
            summary="s",
            strongest="a",
            weakest="b",
            notes=[ANSWER.notes[0]] * 30,
        )

        result = await review_page(PAGE, collect_signals(PAGE), registry=registry(Model(many)))

        assert len(result.as_stored()["notes"]) == 8


class TestБезотказность:
    async def test_сбой_модели_не_роняет_проверку(self) -> None:
        """Проверка сайта без мнения лучше, чем упавшая проверка."""
        broken = Model(AiProviderError("модель недоступна"))
        result = await review_page(PAGE, collect_signals(PAGE), registry=registry(broken))

        assert result.ok is False
        assert "недоступна" in result.reason

    async def test_негодный_ключ_объясняется_отдельно(self) -> None:
        """Ждать и настраивать — разные действия."""
        result = await review_page(
            PAGE, collect_signals(PAGE), registry=registry(Model(AiProviderError("ключ не принят")))
        )

        assert "ключ" in result.reason

    async def test_заглушка_не_выдаётся_за_мнение_модели(self) -> None:
        """Заглушка отвечает валидно по схеме и выдуманно — это её работа."""
        result = await review_page(PAGE, collect_signals(PAGE), registry=registry(StubProvider()))

        assert result.ok is False
        assert "не подключён" in result.reason

    async def test_пустая_страница_модели_не_отправляется(self) -> None:
        """Платить за разбор пустоты незачем."""
        model = Model()
        result = await review_page(
            "<html><body></body></html>", collect_signals(""), registry=registry(model)
        )

        assert result.ok is False
        assert model.seen == []

    async def test_отказ_ложится_в_базу_с_причиной(self) -> None:
        stored = (
            await review_page(PAGE, collect_signals(PAGE), registry=registry(StubProvider()))
        ).as_stored()

        assert stored["available"] is False
        assert stored["reason"]


class TestГраницаСБаллом:
    def test_разбор_не_знает_про_балл(self) -> None:
        """Ошибка модели не должна превращаться в «запускать нельзя».

        Проверяется прямо: в сохраняемом виде нет ни балла, ни вердикта, ни
        признака блокировки — подмешать мнение в оценку просто нечем.
        """
        import ads_os.services.site_review as module

        source = module.__file__
        assert source is not None
        text = pathlib.Path(source).read_text(encoding="utf-8")

        assert "score" not in text
        assert "can_launch" not in text


@pytest.mark.parametrize("topic", list(Topic))
def test_каждая_тема_разбора_названа(topic: Topic) -> None:
    assert topic.value.isascii()
