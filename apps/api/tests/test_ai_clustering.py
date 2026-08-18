"""Группировка фраз моделью.

Главное здесь — что ядро остаётся неприкосновенным. Модель раскладывает фразы,
но не переписывает их и не придумывает новых: она возвращает номера строк, а
всё остальное делает код. Тесты проверяют именно эту границу и починку двух
ошибок, которые модель делает регулярно: несуществующий номер и одна фраза в
двух группах.
"""

from __future__ import annotations

from ads_os.services import ai_clustering
from ads_os.services.ai import (
    AiProviderError,
    AiResult,
    AiUsage,
    ProviderRegistry,
    StubProvider,
)
from ads_os.services.ai_clustering import SuggestedGroup, Suggestion, suggest

PHRASES = [
    "пластиковые окна тверь",
    "купить стеклопакеты",
    "остекление балкона",
    "застеклить лоджию цена",
]

ANSWER = Suggestion(
    groups=[
        SuggestedGroup(name="Окна", lines=[1, 2], reason="Продажа окон."),
        SuggestedGroup(name="Балконы", lines=[3, 4], reason="Остекление балконов."),
    ]
)


class Model:
    """Провайдер, отвечающий заранее заданной раскладкой."""

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
            confidence=0.8,
            reasoning_summary="",
            usage=AiUsage(provider="openai", model="модель-1", input_tokens=40, output_tokens=20),
        )


def registry(provider: object) -> ProviderRegistry:
    return ProviderRegistry(default=provider)  # type: ignore[arg-type]


class TestРаскладка:
    async def test_номера_превращаются_во_фразы(self) -> None:
        result = await suggest(PHRASES, registry=registry(Model()))

        assert result.ok is True
        assert [group.name for group in result.groups] == ["Окна", "Балконы"]
        assert result.groups[0].phrases == ("пластиковые окна тверь", "купить стеклопакеты")

    async def test_разные_слова_об_одном_попадают_вместе(self) -> None:
        """Ради этого модель и зовут: расчёт по общим основам развёл бы
        «стеклопакеты» и «окна» по разным группам."""
        result = await suggest(PHRASES, registry=registry(Model()))

        assert "купить стеклопакеты" in result.groups[0].phrases
        assert "пластиковые окна тверь" in result.groups[0].phrases

    async def test_модель_и_уверенность_сохраняются(self) -> None:
        """Без них человеку нечем оценить, насколько предложению верить."""
        result = await suggest(PHRASES, registry=registry(Model()))

        assert result.confidence == 0.8
        assert result.model == "модель-1"
        assert result.tokens == 60

    async def test_фразы_уходят_помеченными_как_данные(self) -> None:
        model = Model()
        await suggest(PHRASES, registry=registry(model))

        request = model.seen[0]
        assert request.content[0].source == "запросы"  # type: ignore[attr-defined]

    async def test_фразы_нумеруются_с_единицы(self) -> None:
        model = Model()
        await suggest(PHRASES, registry=registry(model))

        text = model.seen[0].content[0].text  # type: ignore[attr-defined]
        assert text.startswith("1. пластиковые окна тверь")


class TestЯдроНеПортится:
    """Ни одна фраза не должна измениться или появиться из ниоткуда."""

    async def test_модель_не_может_добавить_фразу(self) -> None:
        """Она возвращает номера, а не тексты, — придумать нечего."""
        result = await suggest(PHRASES, registry=registry(Model()))

        collected = {phrase for group in result.groups for phrase in group.phrases}
        assert collected <= set(PHRASES)

    async def test_несуществующий_номер_выбрасывается(self) -> None:
        answer = Suggestion(groups=[SuggestedGroup(name="Окна", lines=[1, 99, 0, -3], reason="")])

        result = await suggest(PHRASES, registry=registry(Model(answer)))

        assert result.groups[0].phrases == ("пластиковые окна тверь",)

    async def test_фраза_из_двух_групп_достаётся_первой(self) -> None:
        """Иначе одна фраза уехала бы в две группы кампании и конкурировала бы
        сама с собой, поднимая цену клика."""
        answer = Suggestion(
            groups=[
                SuggestedGroup(name="Первая", lines=[1, 2], reason=""),
                SuggestedGroup(name="Вторая", lines=[2, 3], reason=""),
            ]
        )

        result = await suggest(PHRASES, registry=registry(Model(answer)))

        assert "купить стеклопакеты" in result.groups[0].phrases
        assert "купить стеклопакеты" not in result.groups[1].phrases

    async def test_потерянные_фразы_не_пропадают(self) -> None:
        """Фраза, исчезнувшая из раскладки, исчезла бы и из кампании."""
        answer = Suggestion(groups=[SuggestedGroup(name="Окна", lines=[1], reason="")])

        result = await suggest(PHRASES, registry=registry(Model(answer)))

        assert result.groups[-1].name == "Не разложено моделью"
        assert set(result.groups[-1].phrases) == set(PHRASES[1:])

    async def test_все_фразы_на_месте(self) -> None:
        answer = Suggestion(
            groups=[
                SuggestedGroup(name="Первая", lines=[1, 1, 1], reason=""),
                SuggestedGroup(name="Пустая", lines=[], reason=""),
            ]
        )

        result = await suggest(PHRASES, registry=registry(Model(answer)))

        collected = [phrase for group in result.groups for phrase in group.phrases]
        assert sorted(collected) == sorted(PHRASES)

    async def test_группа_без_фраз_не_показывается(self) -> None:
        answer = Suggestion(
            groups=[
                SuggestedGroup(name="Окна", lines=[1, 2, 3, 4], reason=""),
                SuggestedGroup(name="Пустая", lines=[], reason=""),
            ]
        )

        result = await suggest(PHRASES, registry=registry(Model(answer)))

        assert [group.name for group in result.groups] == ["Окна"]

    async def test_больше_сорока_групп_не_берём(self) -> None:
        """По группе на фразу — формально верно и для кампании бесполезно."""
        many = [f"фраза {i}" for i in range(60)]
        answer = Suggestion(
            groups=[SuggestedGroup(name=f"Г{i}", lines=[i + 1], reason="") for i in range(60)]
        )

        result = await suggest(many, registry=registry(Model(answer)))

        # Сорок групп модели плюс одна с остатком — и остаток не потерян.
        assert len(result.groups) == ai_clustering.MAX_GROUPS + 1
        assert len(result.groups[-1].phrases) == 60 - ai_clustering.MAX_GROUPS


class TestОтказы:
    async def test_заглушка_не_выдаётся_за_разбор(self) -> None:
        """Заглушка отвечает по схеме, но выдуманным. Предложить это как
        раскладку значило бы предложить перестроить кампанию по случайным
        числам."""
        result = await suggest(PHRASES, registry=registry(StubProvider()))

        assert result.ok is False
        assert "не подключена" in result.reason

    async def test_сбой_провайдера_не_роняет_вызов(self) -> None:
        """Группировка моделью дополняет расчёт, а не заменяет его: при отказе
        существующая раскладка остаётся на месте."""
        result = await suggest(
            PHRASES, registry=registry(Model(AiProviderError("модель перегружена")))
        )

        assert result.ok is False
        assert result.reason

    async def test_неожиданная_ошибка_тоже_не_роняет(self) -> None:
        result = await suggest(PHRASES, registry=registry(Model(TimeoutError("сеть"))))

        assert result.ok is False
        assert result.reason

    async def test_одной_фразы_для_группировки_мало(self) -> None:
        result = await suggest(["окна"], registry=registry(Model()))

        assert result.ok is False
        assert "две фразы" in result.reason

    async def test_пустые_строки_не_считаются(self) -> None:
        result = await suggest(["окна", "   ", ""], registry=registry(Model()))

        assert result.ok is False

    async def test_у_отказа_всегда_есть_причина(self) -> None:
        """Пустое место без объяснения человек читает как поломку."""
        for provider in (StubProvider(), Model(AiProviderError("нет ключа"))):
            result = await suggest(PHRASES, registry=registry(provider))

            assert result.reason


class TestПределы:
    async def test_длинный_список_обрезается(self) -> None:
        """Обрезанный ответ модели означал бы потерянные фразы, поэтому режем
        вход, а не ответ."""
        model = Model(Suggestion(groups=[SuggestedGroup(name="Все", lines=[1], reason="")]))
        many = [f"фраза {i}" for i in range(ai_clustering.MAX_PHRASES + 50)]

        result = await suggest(many, registry=registry(model))

        collected = [phrase for group in result.groups for phrase in group.phrases]
        assert len(collected) == ai_clustering.MAX_PHRASES

    async def test_название_группы_не_безразмерное(self) -> None:
        answer = Suggestion(groups=[SuggestedGroup(name="о" * 500, lines=[1, 2], reason="")])

        result = await suggest(PHRASES, registry=registry(Model(answer)))

        assert len(result.groups[0].name) <= 200

    async def test_группа_без_названия_отбрасывается(self) -> None:
        answer = Suggestion(groups=[SuggestedGroup(name="   ", lines=[1, 2], reason="")])

        result = await suggest(PHRASES, registry=registry(Model(answer)))

        assert [group.name for group in result.groups] == ["Не разложено моделью"]
