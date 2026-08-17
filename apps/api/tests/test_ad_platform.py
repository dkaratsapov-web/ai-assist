"""Адаптер рекламной площадки.

Токена нет, боевого аккаунта нет — и это не мешает проверить всё, что зависит
от протокола: заголовки схемы представителя, разбор состояний, микроединицы,
учёт баллов, перевод кодов ошибок в человеческие фразы и предохранитель,
который не даёт уйти в бой раньше времени.

Ответы взяты в форме, которую отдаёт API v5. Когда появится настоящий токен,
эти же тесты покажут, разошлась ли форма с действительностью.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import httpx
import pytest

from ads_os.config import Settings
from ads_os.services.ad_platform import (
    AdPlatformError,
    AuthError,
    CampaignState,
    MockAdapter,
    NotClearedForLiveError,
    QuotaError,
    YandexDirectAdapter,
    get_ad_platform,
)
from ads_os.services.ad_platform.yandex_direct import PRODUCTION_URL, SANDBOX_URL

UNITS = "10/24990/25000"


def transport(handler):  # type: ignore[no-untyped-def]
    """Клиент, который никуда не ходит: ответы задаёт тест."""
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def json_response(payload: dict[str, object], *, units: str | None = UNITS) -> httpx.Response:
    headers = {"Units": units} if units else {}
    return httpx.Response(200, json=payload, headers=headers)


def adapter(handler, **kwargs) -> YandexDirectAdapter:  # type: ignore[no-untyped-def]
    return YandexDirectAdapter(
        token="secret-token",
        login="audit-karatsapov",
        client=transport(handler),
        **kwargs,
    )


class TestСхемаПредставителя:
    """Токен один, рекламодателей много — различает их заголовок."""

    async def test_логин_рекламодателя_уходит_заголовком(self) -> None:
        seen: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen.update(request.headers)
            return json_response({"result": {"Campaigns": []}})

        await adapter(handler).campaigns("sfera-vitamin")

        assert seen["client-login"] == "sfera-vitamin"

    async def test_без_рекламодателя_подставляется_главный_аккаунт(self) -> None:
        """Иначе запрос уходит на аккаунт представителя и молча отдаёт пусто."""
        seen: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen.update(request.headers)
            return json_response({"result": {"Clients": []}})

        await adapter(handler).advertisers()

        assert seen["client-login"] == "audit-karatsapov"

    async def test_токен_уходит_в_заголовке_авторизации(self) -> None:
        seen: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen.update(request.headers)
            return json_response({"result": {"Clients": []}})

        await adapter(handler).advertisers()

        assert seen["authorization"] == "Bearer secret-token"

    async def test_ошибки_запрашиваются_по_русски(self) -> None:
        """Текст ошибки попадает в интерфейс — переводить его на лету было бы
        ещё одним местом, где формулировка расходится."""
        seen: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen.update(request.headers)
            return json_response({"result": {"Clients": []}})

        await adapter(handler).advertisers()

        assert seen["accept-language"] == "ru"


class TestПесочница:
    def test_по_умолчанию_песочница(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert str(request.url).startswith(SANDBOX_URL)
            return json_response({"result": {"Clients": []}})

        assert adapter(handler).is_live is False

    async def test_боевой_режим_обозначен_явно(self) -> None:
        """Продукт обязан показывать это человеку, а не выяснять по косвенным
        признакам."""
        urls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            urls.append(str(request.url))
            return json_response({"result": {"Clients": []}})

        live = adapter(handler, sandbox=False)
        await live.advertisers()

        assert live.is_live is True
        assert urls[0].startswith(PRODUCTION_URL)


class TestРекламодатели:
    async def test_разбираются_из_ответа(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return json_response(
                {
                    "result": {
                        "Clients": [
                            {
                                "Login": "sfera-vitamin",
                                "ClientInfo": "Сфера Витамин",
                                "Currency": "RUB",
                                "Grants": [{"Privilege": "EDIT_CAMPAIGNS", "Value": "YES"}],
                            }
                        ]
                    }
                }
            )

        result = await adapter(handler).advertisers()

        assert len(result.advertisers) == 1
        assert result.advertisers[0].login == "sfera-vitamin"
        assert result.advertisers[0].name == "Сфера Витамин"
        assert result.advertisers[0].can_edit is True

    async def test_право_на_правку_не_выдумывается(self) -> None:
        """Без явного разрешения представитель только читает."""

        def handler(request: httpx.Request) -> httpx.Response:
            return json_response(
                {"result": {"Clients": [{"Login": "x", "ClientInfo": "X", "Currency": "RUB"}]}}
            )

        result = await adapter(handler).advertisers()

        assert result.advertisers[0].can_edit is False


class TestКампании:
    def campaigns_response(self, *items: dict[str, object]) -> httpx.Response:
        return json_response({"result": {"Campaigns": list(items)}})

    async def test_бюджет_переводится_из_микроединиц(self) -> None:
        """Пропущенный делитель превращает 1000 ₽ в миллиард, и на экране это
        выглядит как настоящее число."""

        def handler(request: httpx.Request) -> httpx.Response:
            return self.campaigns_response(
                {
                    "Id": 42,
                    "Name": "Поиск",
                    "State": "ON",
                    "Status": "ACCEPTED",
                    "DailyBudget": {"Amount": 1500000000, "Mode": "STANDARD"},
                }
            )

        result = await adapter(handler).campaigns("x")

        assert result.campaigns[0].daily_budget == Decimal("1500.00")

    async def test_без_бюджета_пусто_а_не_ноль(self) -> None:
        """Ноль означал бы «дневной лимит нулевой», то есть кампания не крутится."""

        def handler(request: httpx.Request) -> httpx.Response:
            return self.campaigns_response(
                {"Id": 1, "Name": "Без лимита", "State": "ON", "Status": "ACCEPTED"}
            )

        result = await adapter(handler).campaigns("x")

        assert result.campaigns[0].daily_budget is None

    @pytest.mark.parametrize(
        ("state", "status", "expected"),
        [
            ("ON", "ACCEPTED", CampaignState.RUNNING),
            ("OFF", "ACCEPTED", CampaignState.STOPPED),
            ("SUSPENDED", "ACCEPTED", CampaignState.STOPPED),
            ("ON", "MODERATION", CampaignState.ON_MODERATION),
            ("ON", "REJECTED", CampaignState.REJECTED),
            ("OFF", "DRAFT", CampaignState.DRAFT),
            # Архив важнее всего остального: архивная кампания одновременно
            # «остановлена», и по одному Status это было бы не видно.
            ("ARCHIVED", "ACCEPTED", CampaignState.ARCHIVED),
            ("ARCHIVED", "REJECTED", CampaignState.ARCHIVED),
        ],
    )
    async def test_состояние_сводится_к_понятному(
        self, state: str, status: str, expected: CampaignState
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return self.campaigns_response({"Id": 1, "Name": "К", "State": state, "Status": status})

        result = await adapter(handler).campaigns("x")

        assert result.campaigns[0].state is expected

    async def test_отклонённая_несёт_причину(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return self.campaigns_response(
                {
                    "Id": 1,
                    "Name": "К",
                    "State": "ON",
                    "Status": "REJECTED",
                    "StatusClarification": "Нет политики обработки персональных данных",
                }
            )

        result = await adapter(handler).campaigns("x")

        assert result.campaigns[0].reject_reason


class TestУчётБаллов:
    """У Директа суточный лимит баллов конечен, и при исчерпании работа встаёт
    до полуночи по Москве."""

    async def test_расход_снимается_с_ответа(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return json_response({"result": {"Clients": []}}, units="10/24990/25000")

        result = await adapter(handler).advertisers()

        assert (result.usage.spent, result.usage.rest, result.usage.limit) == (10, 24990, 25000)

    async def test_без_заголовка_нули_а_не_выдумка(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return json_response({"result": {"Clients": []}}, units=None)

        result = await adapter(handler).advertisers()

        assert result.usage.limit == 0

    async def test_испорченный_заголовок_не_роняет_запрос(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return json_response({"result": {"Clients": []}}, units="10/unknown")

        result = await adapter(handler).advertisers()

        assert result.usage.limit == 0

    def test_остаток_на_исходе_виден_заранее(self) -> None:
        from ads_os.services.ad_platform import Usage

        assert Usage(spent=23000, rest=2000, limit=25000).is_low is True
        assert Usage(spent=1000, rest=24000, limit=25000).is_low is False


class TestОшибки:
    def error(self, code: int, string: str = "Ошибка") -> httpx.Response:
        return json_response(
            {"error": {"error_code": code, "error_string": string, "request_id": "abc"}}
        )

    async def test_нет_прав_представителя_это_ошибка_доступа(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return self.error(58)

        with pytest.raises(AuthError) as exc:
            await adapter(handler).campaigns("x")

        assert "доступ" in str(exc.value).lower()

    async def test_кончились_баллы_это_отдельный_случай(self) -> None:
        """Реакция принципиально другая: не «поправьте данные», а «подождите».
        Повтор немедленно ускоряет исчерпание лимита."""

        def handler(request: httpx.Request) -> httpx.Response:
            return self.error(152)

        with pytest.raises(QuotaError) as exc:
            await adapter(handler).campaigns("x")

        assert "балл" in str(exc.value).lower()

    async def test_код_объясняется_словами(self) -> None:
        """«Ошибка 53» не говорит, что делать."""

        def handler(request: httpx.Request) -> httpx.Response:
            return self.error(53)

        with pytest.raises(AuthError) as exc:
            await adapter(handler).advertisers()

        assert "токен" in str(exc.value).lower()
        assert exc.value.request_id == "abc"

    async def test_незнакомый_код_отдаёт_текст_площадки(self) -> None:
        """Он точнее нашего пересказа и обновляется вместе с Директом."""

        def handler(request: httpx.Request) -> httpx.Response:
            return self.error(8000, "Неверное значение параметра")

        with pytest.raises(AdPlatformError) as exc:
            await adapter(handler).campaigns("x")

        assert str(exc.value) == "Неверное значение параметра"

    async def test_временный_сбой_помечается_повторяемым(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return self.error(503, "Сервис временно недоступен")

        with pytest.raises(AdPlatformError) as exc:
            await adapter(handler).campaigns("x")

        assert exc.value.retryable is True

    async def test_ошибка_данных_не_повторяется(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return self.error(8000, "Неверное значение")

        with pytest.raises(AdPlatformError) as exc:
            await adapter(handler).campaigns("x")

        assert exc.value.retryable is False

    async def test_таймаут_объясняется_человеку(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("вышло время")

        with pytest.raises(AdPlatformError) as exc:
            await adapter(handler).campaigns("x")

        assert exc.value.retryable is True
        assert "Директ" in str(exc.value)

    async def test_ответ_не_по_протоколу_не_принимается_за_пустой(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="<html>техработы</html>")

        with pytest.raises(AdPlatformError):
            await adapter(handler).campaigns("x")


class TestОтчёт:
    REPORT = (
        "Date\tCampaignId\tImpressions\tClicks\tCost\tConversions\n"
        "2026-08-15\t42\t1200\t60\t3400.50\t7\n"
        "2026-08-16\t42\t900\t41\t2100.00\t4\n"
    )

    def handler(self, response: httpx.Response):  # type: ignore[no-untyped-def]
        def inner(request: httpx.Request) -> httpx.Response:
            return response

        return inner

    async def test_расход_по_дням_разбирается(self) -> None:
        client = adapter(
            self.handler(httpx.Response(200, text=self.REPORT, headers={"Units": UNITS}))
        )

        result = await client.daily_stats("x", since=date(2026, 8, 15), until=date(2026, 8, 16))

        assert len(result.stats) == 2
        assert result.stats[0].cost == Decimal("3400.50")
        assert result.stats[0].clicks == 60
        assert result.stats[1].on_date == date(2026, 8, 16)

    async def test_отчёт_в_очереди_это_не_нулевой_расход(self) -> None:
        """Иначе экран покажет «денег не потрачено» вместо «данные ещё едут»."""
        client = adapter(self.handler(httpx.Response(201, text="", headers={"retryIn": "30"})))

        with pytest.raises(AdPlatformError) as exc:
            await client.daily_stats("x", since=date(2026, 8, 15), until=date(2026, 8, 16))

        assert exc.value.retryable is True
        assert "30" in str(exc.value)

    async def test_пустой_отчёт_не_ошибка(self) -> None:
        """За период могло не быть показов — это нормальный ответ."""
        header = "Date\tCampaignId\tImpressions\tClicks\tCost\tConversions\n"
        client = adapter(self.handler(httpx.Response(200, text=header)))

        result = await client.daily_stats("x", since=date(2026, 8, 15), until=date(2026, 8, 16))

        assert result.stats == ()

    async def test_битая_строка_пропускается_а_остальные_нет(self) -> None:
        broken = (
            "Date\tCampaignId\tImpressions\tClicks\tCost\tConversions\n"
            "не дата\t42\t1200\t60\t3400.50\t7\n"
            "2026-08-16\t42\t900\t41\t2100.00\t4\n"
        )
        client = adapter(self.handler(httpx.Response(200, text=broken)))

        result = await client.daily_stats("x", since=date(2026, 8, 15), until=date(2026, 8, 16))

        assert len(result.stats) == 1


class TestЗаглушка:
    async def test_отвечает_одинаково(self) -> None:
        """На заглушке идут тесты: «иногда другое число» превратило бы любой
        упавший тест в загадку."""
        first = await MockAdapter().daily_stats("x", since=date(2026, 8, 1), until=date(2026, 8, 3))
        second = await MockAdapter().daily_stats(
            "x", since=date(2026, 8, 1), until=date(2026, 8, 3)
        )

        assert first.stats == second.stats

    async def test_данные_видно_что_ненастоящие(self) -> None:
        result = await MockAdapter().advertisers()

        assert "емонстрац" in result.advertisers[0].name

    async def test_заглушка_не_боевая(self) -> None:
        assert MockAdapter().is_live is False

    async def test_период_наоборот_даёт_пусто(self) -> None:
        result = await MockAdapter().daily_stats(
            "x", since=date(2026, 8, 10), until=date(2026, 8, 1)
        )

        assert result.stats == ()


class TestПредохранитель:
    """v0.4 §2.1: боевой адаптер не выдаётся, пока не пройдены проверки
    безопасности, даже если токен уже лежит в настройках."""

    def settings(self, **kwargs: object) -> Settings:
        return Settings(**kwargs)  # type: ignore[arg-type]

    def test_по_умолчанию_заглушка(self) -> None:
        assert get_ad_platform(self.settings()).name == "mock"

    def test_одного_переключения_адаптера_мало(self) -> None:
        with pytest.raises(NotClearedForLiveError):
            get_ad_platform(
                self.settings(
                    ad_platform_adapter="yandex_direct",
                    yandex_direct_token="есть",
                )
            )

    def test_разрешения_без_токена_тоже_мало(self) -> None:
        with pytest.raises(AdPlatformError) as exc:
            get_ad_platform(
                self.settings(
                    ad_platform_adapter="yandex_direct",
                    ad_platform_live_approved=True,
                )
            )

        assert "токен" in str(exc.value).lower()

    def test_вместе_дают_боевой_адаптер(self) -> None:
        platform = get_ad_platform(
            self.settings(
                ad_platform_adapter="yandex_direct",
                ad_platform_live_approved=True,
                yandex_direct_token="есть",
                yandex_direct_login="audit-karatsapov",
            )
        )

        assert platform.name == "yandex_direct"

    def test_песочница_остаётся_умолчанием_даже_в_бою(self) -> None:
        """Настоящие деньги требуют ещё одного явного решения."""
        platform = get_ad_platform(
            self.settings(
                ad_platform_adapter="yandex_direct",
                ad_platform_live_approved=True,
                yandex_direct_token="есть",
            )
        )

        assert platform.is_live is False

    def test_пустой_токен_не_принимается_адаптером_напрямую(self) -> None:
        """Мимо фабрики адаптер тоже не должен создаваться безоружным."""
        with pytest.raises(AdPlatformError):
            YandexDirectAdapter(token="", login="x")
