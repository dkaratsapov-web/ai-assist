"""Провайдер OpenAI.

Проверяется не то, что запрос уходит, а то, что нельзя выпустить наружу или
принять внутрь. Наружу — персональные данные и внутренние рассуждения. Внутрь —
ответ, не легший в схему: такой ответ должен быть отброшен целиком, а не
доразобран руками (v0.3 §9).
"""

from __future__ import annotations

import json

import httpx
import pytest
from pydantic import BaseModel, ValidationError

from ads_os.config import Settings
from ads_os.services.ai import (
    AiProviderError,
    AiRequest,
    AiTask,
    OpenAiProvider,
    ProviderRegistry,
    SensitiveDataNotAllowedError,
    Sensitivity,
    StubProvider,
    UntrustedContent,
    build_registry,
    parse_routes,
)
from ads_os.services.ai.openai_provider import envelope_schema


class Verdict(BaseModel):
    query: str
    keep: bool
    note: str | None = None


def answer(result: dict[str, object], **extra: object) -> dict[str, object]:
    envelope = {
        "result": result,
        "confidence": 0.8,
        "summary": "Запрос коммерческий: в нём есть слово «купить».",
        "evidence": ["site"],
    }
    envelope.update(extra)
    return {
        "model": "модель-1",
        "choices": [{"message": {"content": json.dumps(envelope)}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 120, "completion_tokens": 30},
    }


def provider(handler: object, **kwargs: object) -> OpenAiProvider:
    return OpenAiProvider(
        # Ключ латиницей: заголовки HTTP не переносят кириллицу, и настоящий
        # ключ её и не содержит.
        "sk-test",
        model=str(kwargs.pop("model", "модель-разбора")),
        bulk_model=str(kwargs.pop("bulk_model", "модель-пачками")),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),  # type: ignore[arg-type]
    )


def request(**kwargs: object) -> AiRequest[Verdict]:
    return AiRequest(
        task=kwargs.pop("task", AiTask.RECOMMENDATION),  # type: ignore[arg-type]
        sensitivity=kwargs.pop("sensitivity", Sensitivity.SAFE_PUBLIC),  # type: ignore[arg-type]
        response_model=Verdict,
        instruction="Оцени запрос.",
        content=(UntrustedContent(source="site", text="купить окна", source_id="s1"),),
        **kwargs,  # type: ignore[arg-type]
    )


def ok(handler_answer: dict[str, object]) -> object:
    return lambda _: httpx.Response(200, json=handler_answer)


class TestРазбор:
    async def test_ответ_приходит_разобранным_по_схеме(self) -> None:
        client = provider(ok(answer({"query": "купить окна", "keep": True, "note": None})))

        result = await client.complete(request())

        assert result.payload.query == "купить окна"
        assert result.payload.keep is True

    async def test_уверенность_и_объяснение_сохраняются(self) -> None:
        """Без уверенности вызывающий код не отличит твёрдый вывод от догадки."""
        client = provider(ok(answer({"query": "q", "keep": True, "note": None})))

        result = await client.complete(request())

        assert result.confidence == 0.8
        assert "коммерческий" in result.reasoning_summary

    async def test_потребление_учитывается(self) -> None:
        """Каждый вызов модели создаёт UsageEvent (v0.4 §13)."""
        client = provider(ok(answer({"query": "q", "keep": True, "note": None})))

        result = await client.complete(request())

        assert result.usage.input_tokens == 120
        assert result.usage.output_tokens == 30
        assert result.usage.model == "модель-1"

    async def test_ответ_мимо_схемы_не_используется(self) -> None:
        """Разбирать свободный текст руками запрещено: ответ отбрасывается."""
        client = provider(ok(answer({"query": "q"})))

        with pytest.raises(ValidationError):
            await client.complete(request())

    async def test_ответ_не_структурой_отклоняется(self) -> None:
        client = provider(
            lambda _: httpx.Response(
                200,
                json={"choices": [{"message": {"content": "конечно, вот ответ"}}]},
            )
        )

        with pytest.raises(AiProviderError):
            await client.complete(request())

    async def test_уверенность_вне_диапазона_приводится_а_не_роняет(self) -> None:
        """Разбор от кривого числа не портится, а вызов уже оплачен."""
        client = provider(ok(answer({"query": "q", "keep": True, "note": None}, confidence=7)))

        assert (await client.complete(request())).confidence == 1.0

    async def test_без_источников_подставляются_свои(self) -> None:
        """Вывод без основания показывать нельзя."""
        client = provider(ok(answer({"query": "q", "keep": True, "note": None}, evidence=[])))

        assert (await client.complete(request())).evidence == ("s1",)


class TestОтказы:
    async def test_отказ_модели_отличается_от_сбоя(self) -> None:
        client = provider(
            lambda _: httpx.Response(
                200, json={"choices": [{"message": {"refusal": "не буду"}}]}
            )
        )

        with pytest.raises(AiProviderError, match="отказалась"):
            await client.complete(request())

    async def test_обрезанный_ответ_не_принимается(self) -> None:
        """Неполный разбор хуже отсутствующего: по нему принимают решения."""
        client = provider(
            lambda _: httpx.Response(
                200,
                json={"choices": [{"message": {"content": "{"}, "finish_reason": "length"}]},
            )
        )

        with pytest.raises(AiProviderError, match="неполон"):
            await client.complete(request())

    async def test_негодный_ключ_объясняется(self) -> None:
        client = provider(lambda _: httpx.Response(401))

        with pytest.raises(AiProviderError, match="ключ"):
            await client.complete(request())

    async def test_перегрузка_повторяется(self) -> None:
        calls: list[int] = []

        def handler(_: httpx.Request) -> httpx.Response:
            calls.append(1)
            if len(calls) < 3:
                return httpx.Response(429)
            return httpx.Response(200, json=answer({"query": "q", "keep": True, "note": None}))

        client = provider(handler)
        with _instant_sleep():
            result = await client.complete(request())

        assert len(calls) == 3
        assert result.payload.query == "q"

    async def test_отказ_по_ключу_не_повторяется(self) -> None:
        """Второй такой же запрос даст такой же отказ, только позже."""
        calls: list[int] = []

        def handler(_: httpx.Request) -> httpx.Response:
            calls.append(1)
            return httpx.Response(403)

        with pytest.raises(AiProviderError):
            await provider(handler).complete(request())

        assert len(calls) == 1


class TestПерсональныеДанные:
    async def test_чувствительные_данные_не_уходят(self) -> None:
        """Проверка есть и в реестре, и здесь: провайдер внешний."""
        client = provider(lambda _: httpx.Response(500))

        with pytest.raises(SensitiveDataNotAllowedError):
            await client.complete(request(sensitivity=Sensitivity.SENSITIVE))


class TestЗапрос:
    async def test_внешний_текст_помечен_данными(self) -> None:
        """Иначе указание со страницы конкурента стало бы указанием модели."""
        seen: dict[str, object] = {}

        def handler(http_request: httpx.Request) -> httpx.Response:
            seen.update(json.loads(http_request.content))
            return httpx.Response(200, json=answer({"query": "q", "keep": True, "note": None}))

        await provider(handler).complete(request())

        prompt = str(seen["messages"][1]["content"])  # type: ignore[index]
        assert "<untrusted" in prompt
        assert prompt.index("ИСХОДНЫЕ ДАННЫЕ") < prompt.index("купить окна")

    async def test_схема_ответа_уходит_вместе_с_запросом(self) -> None:
        seen: dict[str, object] = {}

        def handler(http_request: httpx.Request) -> httpx.Response:
            seen.update(json.loads(http_request.content))
            return httpx.Response(200, json=answer({"query": "q", "keep": True, "note": None}))

        await provider(handler).complete(request())

        fmt = seen["response_format"]
        assert fmt["type"] == "json_schema"  # type: ignore[index]
        assert fmt["json_schema"]["strict"] is True  # type: ignore[index]

    async def test_температура_без_нужды_не_отправляется(self) -> None:
        """Часть моделей отклоняет запрос с любым значением, кроме своего."""
        seen: dict[str, object] = {}

        def handler(http_request: httpx.Request) -> httpx.Response:
            seen.update(json.loads(http_request.content))
            return httpx.Response(200, json=answer({"query": "q", "keep": True, "note": None}))

        await provider(handler).complete(request())

        assert "temperature" not in seen


class TestВыборМодели:
    def test_массовая_задача_идёт_модели_попроще(self) -> None:
        client = provider(lambda _: httpx.Response(200))

        assert client.model_for(request(task=AiTask.AD_GENERATION)) == "модель-пачками"

    def test_разбор_идёт_основной_модели(self) -> None:
        client = provider(lambda _: httpx.Response(200))

        assert client.model_for(request(task=AiTask.WEBSITE_ANALYSIS)) == "модель-разбора"

    def test_явное_указание_главнее_настройки(self) -> None:
        client = provider(lambda _: httpx.Response(200))

        assert client.model_for(request(options={"model": "особая"})) == "особая"


class TestСхемаДляСтрогогоРежима:
    def test_все_поля_обязательны(self) -> None:
        """Требование строгого режима: иначе площадка не гарантирует форму."""
        schema = envelope_schema(Verdict)

        result = schema["properties"]["result"]
        assert set(result["required"]) == {"query", "keep", "note"}

    def test_лишние_поля_запрещены(self) -> None:
        schema = envelope_schema(Verdict)

        assert schema["additionalProperties"] is False
        assert schema["properties"]["result"]["additionalProperties"] is False

    def test_необязательное_поле_остаётся_обнуляемым(self) -> None:
        """Обязательность в схеме не должна заставлять модель выдумывать
        значение там, где его нет."""
        note = envelope_schema(Verdict)["properties"]["result"]["properties"]["note"]

        assert {"type": "null"} in note["anyOf"]

    def test_значения_по_умолчанию_убраны(self) -> None:
        """Строгий режим их не принимает, а проверяем мы всё равно сами."""
        note = envelope_schema(Verdict)["properties"]["result"]["properties"]["note"]

        assert "default" not in note

    def test_вложенные_схемы_тоже_строгие(self) -> None:
        class Item(BaseModel):
            name: str

        class Batch(BaseModel):
            items: list[Item]

        schema = envelope_schema(Batch)

        assert schema["$defs"]["Item"]["additionalProperties"] is False

    def test_поле_с_именем_properties_не_путается_со_схемой(self) -> None:
        """Обход идёт по местам схемы, а не по всем ключам подряд."""

        class Odd(BaseModel):
            properties: str
            type: str

        result = envelope_schema(Odd)["properties"]["result"]

        assert set(result["required"]) == {"properties", "type"}
        assert result["properties"]["properties"] == {"title": "Properties", "type": "string"}


class TestПодключение:
    def test_по_умолчанию_работает_заглушка(self) -> None:
        registry = build_registry(Settings(app_env="development"))

        assert registry.resolve(AiTask.RECOMMENDATION, Sensitivity.SAFE_PUBLIC).name == "stub"

    def test_включённый_без_ключа_роняет_запуск(self) -> None:
        """Молчаливый откат на заглушку выдавал бы её выдумки за разбор
        модели, и заметить подмену было бы нечем."""
        with pytest.raises(ValueError, match="ключ не задан"):
            build_registry(Settings(app_env="development", ai_provider="openai"))

    def test_включённый_с_ключом_работает(self) -> None:
        registry = build_registry(
            Settings(app_env="development", ai_provider="openai", openai_api_key="ключ")
        )

        assert registry.resolve(AiTask.RECOMMENDATION, Sensitivity.SAFE_PUBLIC).name == "openai"

    def test_маршрут_по_задаче_уводит_к_модели(self) -> None:
        """Часть задач может идти модели, а часть — оставаться на заглушке."""
        routes = parse_routes(
            "website_analysis=openai",
            Settings(app_env="development", openai_api_key="ключ"),
        )

        assert routes[AiTask.WEBSITE_ANALYSIS].name == "openai"

    def test_персональные_данные_остаются_запрещёнными(self) -> None:
        """Подключение модели не открывает ей ПДн (v0.4 §2.3)."""
        registry = ProviderRegistry(default=StubProvider())

        with pytest.raises(SensitiveDataNotAllowedError):
            registry.resolve(AiTask.RECOMMENDATION, Sensitivity.SENSITIVE)


def _instant_sleep():  # type: ignore[no-untyped-def]
    """Повторы не должны стоить тесту секунд ожидания."""
    from unittest.mock import AsyncMock, patch

    from ads_os.services.ai import openai_provider

    return patch.object(openai_provider.asyncio, "sleep", AsyncMock())
