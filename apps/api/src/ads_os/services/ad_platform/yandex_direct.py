"""Адаптер Яндекс Директа (API v5).

Написан заранее, до появления токена. Это не работа впустую: протокол Директа
описан, и всё, что от него зависит — заголовки, форма запроса, разбор ошибок,
учёт баллов, — проверяется на записанных ответах без единого обращения наружу.
Когда токен появится, останется переключить настройку, а не писать код в
спешке на боевом аккаунте.

Схема доступа — представитель: токен один, на главный аккаунт, а конкретный
рекламодатель указывается заголовком `Client-Login` в каждом запросе.

Про баллы. У Директа расход API считается в баллах, суточный лимит конечен, и
при его исчерпании площадка перестаёт отвечать до полуночи по Москве. Поэтому
расход снимается с каждого ответа и возвращается наверх, а не игнорируется:
узнать об исчерпании в момент, когда работа уже встала, — поздно.

Чего здесь нет: публикации кампаний и правки ставок. Метод, который ни разу не
выполнялся на настоящем аккаунте, — это обещание, а не функция. Они появятся
вместе с доступом.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import date
from decimal import Decimal
from typing import Any

import httpx

from .contracts import (
    AdPlatformError,
    Advertiser,
    AuthError,
    Campaign,
    CampaignState,
    DailyStats,
    PlatformResponse,
    QuotaError,
    Usage,
)

logger = logging.getLogger(__name__)

PRODUCTION_URL = "https://api.direct.yandex.com/json/v5"
SANDBOX_URL = "https://api-sandbox.direct.yandex.com/json/v5"

#: Директ отдаёт деньги в микроединицах валюты: миллион — это один рубль.
#: Делить на месте вызова нельзя: один пропущенный делитель превращает 1000 ₽
#: в миллиард, и на экране это выглядит как настоящее число.
MICRO = Decimal(1_000_000)

#: Коды, при которых виноват не запрос, а доступ. Список из документации API v5.
_AUTH_CODES = frozenset({53, 54, 55, 58, 512, 513})

#: Коды исчерпания баллов и превышения частоты обращений.
_QUOTA_CODES = frozenset({152, 506, 1001, 1002, 1022})

#: Коды, при которых повтор того же запроса имеет смысл: временный сбой
#: площадки. Остальное повторять бессмысленно — ответ не изменится.
_RETRYABLE_CODES = frozenset({52, 500, 501, 502, 503, 504, 9000})

_MESSAGES: dict[int, str] = {
    53: "Токен Директа не принят. Проверьте, что он не истёк и выпущен для этого приложения.",
    54: "У токена нет доступа к API Директа. Проверьте, одобрена ли заявка на доступ.",
    55: "Пользователь заблокирован в Директе.",
    58: (
        "Нет прав представителя на этого рекламодателя. Клиент должен выдать доступ "
        "главному аккаунту."
    ),
    152: (
        "Закончились баллы API Директа на сегодня. Лимит обновляется в полночь "
        "по московскому времени."
    ),
    506: "Слишком много запросов к Директу подряд. Нужна пауза.",
    513: "Указанный рекламодатель недоступен по этому токену.",
}


def _state(raw: dict[str, Any]) -> CampaignState:
    """Сводит `State` и `Status` Директа к одному состоянию для экрана.

    Порядок проверок важен: архивная кампания одновременно «остановлена», а
    отклонённая — «включена». Человека интересует главное препятствие, а не
    полный набор флагов.
    """
    state = str(raw.get("State") or "").upper()
    status = str(raw.get("Status") or "").upper()

    if state == "ARCHIVED":
        return CampaignState.ARCHIVED
    if status == "REJECTED":
        return CampaignState.REJECTED
    if status == "MODERATION":
        return CampaignState.ON_MODERATION
    if status == "DRAFT":
        return CampaignState.DRAFT
    if state == "ON":
        return CampaignState.RUNNING
    return CampaignState.STOPPED


def _money(value: Any) -> Decimal | None:
    """Микроединицы Директа в рубли."""
    if value in (None, ""):
        return None
    try:
        return (Decimal(str(value)) / MICRO).quantize(Decimal("0.01"))
    except (ArithmeticError, ValueError):
        return None


def _usage(headers: httpx.Headers) -> Usage:
    """Расход баллов из заголовка `Units`.

    Формат — «израсходовано/осталось/суточный лимит». Заголовка может не быть
    (например, у ответа с ошибкой транспорта) — тогда нули, а не выдумка.
    """
    raw = headers.get("Units") or headers.get("units")
    if not raw:
        return Usage()

    parts = raw.split("/")
    if len(parts) != 3:
        return Usage()

    try:
        return Usage(spent=int(parts[0]), rest=int(parts[1]), limit=int(parts[2]))
    except ValueError:
        return Usage()


class YandexDirectAdapter:
    """Чтение из Яндекс Директа."""

    name = "yandex_direct"

    def __init__(
        self,
        *,
        token: str,
        login: str,
        sandbox: bool = True,
        client: httpx.AsyncClient | None = None,
        timeout: float = 30.0,
    ) -> None:
        if not token:
            # Пустой токен — не «ещё не настроено», а ошибка конфигурации:
            # адаптер выбран явно, значит от него ждут работы.
            raise AdPlatformError("Не задан токен Яндекс Директа")

        self._token = token
        self._login = login
        self._sandbox = sandbox
        self._base = SANDBOX_URL if sandbox else PRODUCTION_URL
        self._client = client
        self._timeout = timeout

        #: Песочница деньгами не распоряжается, боевой аккаунт — распоряжается.
        self.is_live = not sandbox

    async def advertisers(self) -> PlatformResponse:
        payload, usage = await self._call(
            "agencyclients",
            {
                "method": "get",
                "params": {
                    "FieldNames": ["Login", "ClientInfo", "Currency", "Grants"],
                    "Page": {"Limit": 200},
                },
            },
        )

        items = payload.get("Clients") or []
        return PlatformResponse(
            advertisers=tuple(
                Advertiser(
                    login=str(item.get("Login") or ""),
                    name=str(item.get("ClientInfo") or item.get("Login") or ""),
                    currency=str(item.get("Currency") or ""),
                    can_edit=any(
                        g.get("Privilege") == "EDIT_CAMPAIGNS" and g.get("Value") == "YES"
                        for g in item.get("Grants") or []
                    ),
                )
                for item in items
            ),
            usage=usage,
        )

    async def campaigns(self, advertiser_login: str) -> PlatformResponse:
        payload, usage = await self._call(
            "campaigns",
            {
                "method": "get",
                "params": {
                    "SelectionCriteria": {},
                    "FieldNames": ["Id", "Name", "State", "Status", "DailyBudget"],
                    "Page": {"Limit": 1000},
                },
            },
            client_login=advertiser_login,
        )

        items = payload.get("Campaigns") or []
        return PlatformResponse(
            campaigns=tuple(
                Campaign(
                    id=int(item["Id"]),
                    name=str(item.get("Name") or ""),
                    state=_state(item),
                    daily_budget=_money((item.get("DailyBudget") or {}).get("Amount")),
                    reject_reason=item.get("StatusClarification"),
                )
                for item in items
                if item.get("Id") is not None
            ),
            usage=usage,
        )

    async def daily_stats(
        self, advertiser_login: str, *, since: date, until: date
    ) -> PlatformResponse:
        """Расход по дням.

        Отчёты в Директе живут на отдельной ручке и отдают TSV, а не JSON.
        Режим выбран синхронный: периоды, которые нужны экранам, укладываются в
        него, а асинхронный требует опроса и очереди на стороне площадки.
        """
        body = {
            "params": {
                "SelectionCriteria": {
                    "DateFrom": since.isoformat(),
                    "DateTo": until.isoformat(),
                },
                "FieldNames": [
                    "Date",
                    "CampaignId",
                    "Impressions",
                    "Clicks",
                    "Cost",
                    "Conversions",
                ],
                "ReportName": f"ads-os {since.isoformat()} {until.isoformat()}",
                "ReportType": "CAMPAIGN_PERFORMANCE_REPORT",
                "DateRangeType": "CUSTOM_DATE",
                "Format": "TSV",
                "IncludeVAT": "YES",
                "IncludeDiscount": "NO",
            }
        }

        text, usage = await self._call_report(body, client_login=advertiser_login)
        return PlatformResponse(stats=_parse_report(text), usage=usage)

    # ── транспорт ────────────────────────────────────────────────────────────

    def _headers(self, client_login: str | None) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._token}",
            # Ошибки приходят на языке из этого заголовка. Русский выбран не для
            # красоты: текст ошибки попадает в интерфейс, и переводить его на
            # лету было бы ещё одним местом, где формулировка может разойтись.
            "Accept-Language": "ru",
            "Content-Type": "application/json; charset=utf-8",
        }
        # Логин рекламодателя. Без него запрос уходит на аккаунт представителя,
        # у которого своих кампаний нет, и ответ будет пустым — молча.
        login = client_login or self._login
        if login:
            headers["Client-Login"] = login
        return headers

    async def _request(
        self, path: str, body: dict[str, Any], *, headers: dict[str, str]
    ) -> httpx.Response:
        client = self._client
        if client is not None:
            return await client.post(f"{self._base}/{path}", json=body, headers=headers)

        async with httpx.AsyncClient(timeout=self._timeout) as owned:
            return await owned.post(f"{self._base}/{path}", json=body, headers=headers)

    async def _call(
        self, path: str, body: dict[str, Any], *, client_login: str | None = None
    ) -> tuple[dict[str, Any], Usage]:
        try:
            response = await self._request(path, body, headers=self._headers(client_login))
        except httpx.TimeoutException as exc:
            raise AdPlatformError(
                "Директ не ответил вовремя. Попробуйте ещё раз через несколько минут.",
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise AdPlatformError("Не удалось связаться с Директом.", retryable=True) from exc

        usage = _usage(response.headers)

        try:
            payload = response.json()
        except ValueError as exc:
            raise AdPlatformError(
                f"Директ ответил не по протоколу (код {response.status_code}).",
                retryable=response.status_code >= 500,
            ) from exc

        if "error" in payload:
            raise _to_error(payload["error"])

        result = payload.get("result")
        if not isinstance(result, dict):
            raise AdPlatformError("Директ вернул ответ без результата.")

        return result, usage

    async def _call_report(self, body: dict[str, Any], *, client_login: str) -> tuple[str, Usage]:
        headers = self._headers(client_login) | {
            "processingMode": "auto",
            "returnMoneyInMicros": "false",
            "skipReportHeader": "true",
            "skipReportSummary": "true",
        }

        try:
            response = await self._request("reports", body, headers=headers)
        except httpx.TimeoutException as exc:
            raise AdPlatformError(
                "Директ не успел собрать отчёт. Попробуйте меньший период.", retryable=True
            ) from exc
        except httpx.HTTPError as exc:
            raise AdPlatformError("Не удалось связаться с Директом.", retryable=True) from exc

        usage = _usage(response.headers)

        # 201 и 202 означают, что отчёт поставлен в очередь и ещё не готов.
        # Это не ошибка и не пустой отчёт: вернуть здесь ноль расходов значило
        # бы показать «денег не потрачено» вместо «данные ещё едут».
        if response.status_code in (201, 202):
            wait = response.headers.get("retryIn") or "60"
            raise AdPlatformError(
                f"Директ ещё готовит отчёт. Данные появятся примерно через {wait} с.",
                retryable=True,
            )

        if response.status_code >= 400:
            try:
                raise _to_error(response.json().get("error") or {})
            except ValueError as exc:
                raise AdPlatformError(
                    f"Директ отказал в отчёте (код {response.status_code}).",
                    retryable=response.status_code >= 500,
                ) from exc

        return response.text, usage


def _to_error(raw: dict[str, Any]) -> AdPlatformError:
    """Ошибку площадки — в человеческую формулировку.

    Свой текст берётся там, где текст Директа непонятен без контекста. Где он
    внятен, отдаём его: он точнее нашего пересказа и обновляется вместе с
    площадкой.
    """
    try:
        code = int(raw.get("error_code") or 0)
    except (TypeError, ValueError):
        code = 0

    detail = str(raw.get("error_detail") or "") or None
    request_id = str(raw.get("request_id") or "") or None
    message = _MESSAGES.get(code) or str(raw.get("error_string") or "Директ отклонил запрос")

    if code in _AUTH_CODES:
        return AuthError(message, code=code, detail=detail, request_id=request_id)
    if code in _QUOTA_CODES:
        return QuotaError(message, code=code, detail=detail, request_id=request_id)

    return AdPlatformError(
        message,
        code=code,
        detail=detail,
        request_id=request_id,
        retryable=code in _RETRYABLE_CODES,
    )


def _parse_report(text: str) -> tuple[DailyStats, ...]:
    """Разбирает TSV-отчёт.

    Строки с непонятными значениями пропускаются молча — но только они. Пустой
    отчёт и отчёт из мусора должны выглядеть по-разному: первый означает «за
    период показов не было», второй — что мы неправильно разобрали ответ.
    """
    rows: list[DailyStats] = []
    reader = csv.DictReader(io.StringIO(text), delimiter="\t")

    for row in reader:
        try:
            rows.append(
                DailyStats(
                    campaign_id=int(row["CampaignId"]),
                    on_date=date.fromisoformat(row["Date"]),
                    impressions=int(row.get("Impressions") or 0),
                    clicks=int(row.get("Clicks") or 0),
                    cost=Decimal(row.get("Cost") or "0"),
                    conversions=int(row["Conversions"]) if row.get("Conversions") else None,
                )
            )
        except (KeyError, TypeError, ValueError, ArithmeticError):
            logger.warning("строка отчёта Директа не разобрана", extra={"row": str(row)[:200]})

    return tuple(rows)
