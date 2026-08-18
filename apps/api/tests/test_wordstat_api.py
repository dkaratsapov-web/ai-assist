"""Клиент Вордстата.

Проверяется главным образом то, как объясняются отказы. Кончившаяся квота и
отозванный доступ требуют разных действий, а по числам 429 и 403 это понимает
не каждый — и человек, увидевший «ошибка 429», идёт спрашивать вместо того,
чтобы подождать час.
"""

from __future__ import annotations

import httpx
import pytest

from ads_os.config import Settings
from ads_os.services.wordstat_api import (
    MAX_PHRASES,
    NotConfiguredError,
    NullSource,
    WordstatError,
    YandexWordstat,
    get_source,
)

ANSWER = {
    "totalCount": "48200",
    "results": [
        {"phrase": "натяжные потолки тверь", "count": "5400"},
        {"phrase": "натяжные потолки цена", "count": "3100"},
    ],
    "associations": [{"phrase": "потолки под ключ", "count": "900"}],
}


def source(handler: object) -> YandexWordstat:
    transport = httpx.MockTransport(handler)  # type: ignore[arg-type]
    return YandexWordstat(
        "api-key-value",
        "folder-1",
        client=httpx.AsyncClient(transport=transport),
    )


class TestЗапрос:
    async def test_отдаёт_фразы_с_частотностями(self) -> None:
        client = source(lambda request: httpx.Response(200, json=ANSWER))

        result = await client.top("натяжные потолки")

        assert result.total == 48200
        assert result.results[0].phrase == "натяжные потолки тверь"
        assert result.results[0].count == 5400

    async def test_похожие_запросы_отдельно(self) -> None:
        """Их площадка отдаёт не больше двадцати: это подсказка, куда смотреть,
        а не список для сбора."""
        client = source(lambda request: httpx.Response(200, json=ANSWER))

        result = await client.top("натяжные потолки")

        assert result.associations[0].phrase == "потолки под ключ"

    async def test_числа_передаются_строками(self) -> None:
        """Формат этого API: число вместо строки — отказ с невнятным текстом."""
        seen: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen.update(__import__("json").loads(request.content))
            return httpx.Response(200, json=ANSWER)

        await source(handler).top("окна", num_phrases=300)

        assert seen["numPhrases"] == "300"

    async def test_каталог_уходит_в_каждом_запросе(self) -> None:
        seen: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen.update(__import__("json").loads(request.content))
            return httpx.Response(200, json=ANSWER)

        await source(handler).top("окна")

        assert seen["folderId"] == "folder-1"

    async def test_число_фраз_ограничено_пределом_площадки(self) -> None:
        """Просить больше — получить отказ вместо данных."""
        seen: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen.update(__import__("json").loads(request.content))
            return httpx.Response(200, json=ANSWER)

        await source(handler).top("окна", num_phrases=99_999)

        assert seen["numPhrases"] == str(MAX_PHRASES)

    async def test_регионы_передаются_когда_заданы(self) -> None:
        seen: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen.update(__import__("json").loads(request.content))
            return httpx.Response(200, json=ANSWER)

        await source(handler).top("окна", regions=("213",))

        assert seen["regions"] == ["213"]

    async def test_пустая_маска_не_отправляется(self) -> None:
        with pytest.raises(WordstatError):
            await source(lambda request: httpx.Response(200, json=ANSWER)).top("   ")


class TestАвторизация:
    async def test_постоянный_ключ(self) -> None:
        seen: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["auth"] = request.headers["Authorization"]
            return httpx.Response(200, json=ANSWER)

        await source(handler).top("окна")

        assert seen["auth"] == "Api-Key api-key-value"

    async def test_временный_токен_узнаётся_по_виду(self) -> None:
        """Спрашивать вид ключа отдельной настройкой значит завести поле,
        которое разойдётся с тем, что реально вставлено."""
        seen: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["auth"] = request.headers["Authorization"]
            return httpx.Response(200, json=ANSWER)

        client = YandexWordstat(
            "t1.abcdef",
            "folder-1",
            client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        await client.top("окна")

        assert seen["auth"] == "Bearer t1.abcdef"


class TestОтказы:
    async def test_кончившаяся_квота_объясняется_и_повторяема(self) -> None:
        client = source(lambda request: httpx.Response(429))

        with pytest.raises(WordstatError) as error:
            await client.top("окна")

        assert error.value.retryable is True
        assert "квота" in error.value.reason.lower()

    async def test_отозванный_доступ_повторять_бессмысленно(self) -> None:
        client = source(lambda request: httpx.Response(403))

        with pytest.raises(WordstatError) as error:
            await client.top("окна")

        assert error.value.retryable is False
        assert "роль" in error.value.reason.lower()

    async def test_сбой_площадки_повторяем(self) -> None:
        client = source(lambda request: httpx.Response(503))

        with pytest.raises(WordstatError) as error:
            await client.top("окна")

        assert error.value.retryable is True

    async def test_обрыв_сети_повторяем(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("нет связи")

        with pytest.raises(WordstatError) as error:
            await source(handler).top("окна")

        assert error.value.retryable is True

    async def test_мусор_вместо_ответа(self) -> None:
        client = source(lambda request: httpx.Response(200, content=b"<html>"))

        with pytest.raises(WordstatError):
            await client.top("окна")


class TestВыборИсточника:
    def test_по_умолчанию_источника_нет(self) -> None:
        assert isinstance(get_source(Settings(app_env="development")), NullSource)

    def test_включённый_без_ключа_остаётся_выключенным(self) -> None:
        """Иначе система молча делала бы запросы, которые всегда отклоняются."""
        settings = Settings(app_env="development", wordstat_provider="yandex")

        assert isinstance(get_source(settings), NullSource)

    def test_включённый_с_ключом_работает(self) -> None:
        settings = Settings(
            app_env="development",
            wordstat_provider="yandex",
            yandex_wordstat_token="key",
            yandex_cloud_folder_id="folder",
        )

        assert isinstance(get_source(settings), YandexWordstat)

    async def test_без_источника_ошибка_говорит_что_делать(self) -> None:
        with pytest.raises(NotConfiguredError) as error:
            await NullSource().top("окна")

        assert "вручную" in str(error.value)
