"""Источник частотностей: Вордстат через Search API Яндекс Облака.

До сих пор частотности приходили только выгрузкой, которую человек делал
руками. Этот модуль добавляет второй источник — тот же Вордстат, но по запросу
из кода. Ручной путь остаётся: у Key Collector своя глубина, а квота здесь
кончается, и в этот момент нужно чем-то работать.

Что важно знать про этот источник, прежде чем на него закладываться.

**Сто запросов в час.** Не в минуту и не в секунду — в час, на весь сервис
целиком. Это главное число: оно означает, что сбор не может быть кнопкой
«собрать сейчас», за которой человек ждёт. Он ставится заданием и растягивается
во времени, а собранное сохраняется по мере поступления, а не в конце.

**Одна маска — до двух тысяч фраз.** Ограничение в двадцать штук, которое легко
принять за предел ответа, относится только к «ассоциациям» — похожим запросам
из правой колонки. Основной список ограничен параметром `numPhrases`, и там
предел две тысячи. Поэтому десяти масок хватает на полноценное ядро.

**Доступ идёт через Облако, а не через рекламный кабинет.** Нужен каталог и
роль, дающая право на поисковые запросы. Токен здесь не имеет никакого
отношения к деньгам клиента: Вордстат только читает статистику и ничего не
может изменить ни в одной кампании.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from ..config import Settings, get_settings

logger = logging.getLogger(__name__)

TOP_URL = "https://searchapi.api.cloud.yandex.net/v2/wordstat/topRequests"

#: Сколько ждём ответа. Сбор идёт в фоне, спешить некуда, но и висеть на
#: неотвечающем сервисе, занимая место в очереди, незачем.
TIMEOUT_SECONDS = 30.0

#: Предел, заданный площадкой. Просить больше — получить отказ вместо данных.
MAX_PHRASES = 2000
MAX_PHRASE_LENGTH = 400
MAX_REGIONS = 100

#: Сколько фраз запрашиваем по умолчанию. Не предел: две тысячи фраз на маску —
#: это список, который человек не прочитает, а чистить его придётся всё равно.
#: Пятьсот дают ядро с хвостом и оставляют разбор обозримым.
DEFAULT_PHRASES = 500

#: Квота площадки. Держится здесь, а не в настройках: это не наш выбор, а
#: ограничение сервиса, и менять его через переменную окружения бессмысленно —
#: оно от этого не изменится.
REQUESTS_PER_HOUR = 100
REQUESTS_PER_SECOND = 10


@dataclass(frozen=True, slots=True)
class Phrase:
    """Запрос и сколько раз его искали за последние тридцать дней."""

    phrase: str
    count: int


@dataclass(frozen=True, slots=True)
class TopResult:
    """Ответ на одну маску."""

    #: Сколько всего запросов содержат все слова маски, в любом порядке. Это
    #: базовая частотность самой маски — по ней видно объём темы целиком.
    total: int
    #: Основной список: запросы, содержащие маску.
    results: tuple[Phrase, ...] = field(default_factory=tuple)
    #: Похожие запросы. Их площадка отдаёт не больше двадцати, и это не список
    #: для сбора, а подсказка, куда смотреть дальше: другие названия услуги,
    #: смежные темы, чужие формулировки.
    associations: tuple[Phrase, ...] = field(default_factory=tuple)


class WordstatError(Exception):
    """Обращение к Вордстату не удалось."""

    def __init__(self, reason: str, *, retryable: bool = False) -> None:
        super().__init__(reason)
        self.reason = reason
        #: Кончилась квота или площадка не ответила — имеет смысл повторить
        #: позже. Неверный запрос или отозванный доступ — не имеет.
        self.retryable = retryable


class NotConfiguredError(WordstatError):
    """Источник не подключён."""

    def __init__(self) -> None:
        super().__init__(
            "Сбор частотностей не подключён. Пока источника нет, частотности "
            "берутся из выгрузки, сделанной вручную."
        )


class WordstatSource(Protocol):
    """Откуда берутся частотности."""

    async def top(
        self, phrase: str, *, regions: tuple[str, ...] = (), num_phrases: int = DEFAULT_PHRASES
    ) -> TopResult: ...


class NullSource:
    """Источника нет.

    Отдельный класс, а не None, чтобы вызывающий код не обрастал проверками
    «а подключено ли». Ошибка при этом внятная и говорит, что делать.
    """

    async def top(
        self, phrase: str, *, regions: tuple[str, ...] = (), num_phrases: int = DEFAULT_PHRASES
    ) -> TopResult:
        raise NotConfiguredError()


class YandexWordstat:
    """Вордстат через Search API Яндекс Облака."""

    def __init__(
        self,
        token: str,
        folder_id: str,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._token = token
        self._folder_id = folder_id
        self._client = client

    @property
    def _authorization(self) -> str:
        """Заголовок авторизации.

        Облако принимает два вида ключей, и различаются они видом самой строки:
        временный токен доступа начинается с «t1.», постоянный ключ сервисного
        аккаунта — нет. Спрашивать это отдельной настройкой значит завести поле,
        которое рано или поздно разойдётся с тем, что реально вставлено.
        """
        if self._token.startswith("t1."):
            return f"Bearer {self._token}"
        return f"Api-Key {self._token}"

    async def top(
        self, phrase: str, *, regions: tuple[str, ...] = (), num_phrases: int = DEFAULT_PHRASES
    ) -> TopResult:
        text = phrase.strip()[:MAX_PHRASE_LENGTH]
        if not text:
            raise WordstatError("пустая маска")

        payload: dict[str, Any] = {
            "phrase": text,
            # Числа в этом API передаются строками — так устроен его формат.
            # Отправив число, получаем отказ с невнятным сообщением.
            "numPhrases": str(max(1, min(num_phrases, MAX_PHRASES))),
            "folderId": self._folder_id,
        }
        if regions:
            payload["regions"] = list(regions[:MAX_REGIONS])

        client = self._client or httpx.AsyncClient(timeout=TIMEOUT_SECONDS)
        owned = self._client is None

        try:
            response = await client.post(
                TOP_URL,
                json=payload,
                headers={"Authorization": self._authorization},
            )
        except httpx.HTTPError as error:
            raise WordstatError(f"сеть: {type(error).__name__}", retryable=True) from error
        finally:
            if owned:
                await client.aclose()

        return _parse(response, phrase=text)


def _parse(response: httpx.Response, *, phrase: str) -> TopResult:
    """Разбирает ответ, переводя коды площадки в понятные причины.

    Причина важнее кода: «кончилась квота» и «доступ отозван» требуют разных
    действий, а по числу 429 против 403 это понимает не каждый.
    """
    if response.status_code == 429:
        raise WordstatError(
            "Квота Вордстата на этот час исчерпана: сто запросов в час на весь "
            "сервис. Сбор продолжится автоматически, когда лимит обновится.",
            retryable=True,
        )

    if response.status_code in (401, 403):
        raise WordstatError(
            "Доступ к Вордстату отклонён. Проверьте ключ и права: нужна роль на "
            "поисковые запросы в том каталоге, который указан в настройках."
        )

    if response.status_code >= 500:
        raise WordstatError(
            f"Вордстат не отвечает (код {response.status_code})", retryable=True
        )

    if response.status_code != 200:
        raise WordstatError(f"Вордстат ответил кодом {response.status_code}")

    try:
        data = response.json()
    except ValueError as error:
        raise WordstatError("Вордстат вернул не разбираемый ответ") from error

    logger.info(
        "частотности получены",
        extra={"phrase": phrase[:100], "found": len(data.get("results") or [])},
    )

    return TopResult(
        total=_number(data.get("totalCount")),
        results=_phrases(data.get("results")),
        associations=_phrases(data.get("associations")),
    )


def _phrases(raw: Any) -> tuple[Phrase, ...]:
    if not isinstance(raw, list):
        return ()

    found: list[Phrase] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        text = str(item.get("phrase") or "").strip()
        if text:
            found.append(Phrase(phrase=text, count=_number(item.get("count"))))
    return tuple(found)


def _number(raw: Any) -> int:
    """Числа приходят строками — таков формат этого API."""
    try:
        return int(str(raw))
    except (TypeError, ValueError):
        return 0


def get_source(settings: Settings | None = None) -> WordstatSource:
    """Возвращает источник частотностей по настройкам.

    По умолчанию источника нет, и это не поломка: система работает на выгрузке,
    сделанной руками, и честно об этом говорит.
    """
    settings = settings or get_settings()

    if settings.wordstat_provider != "yandex":
        return NullSource()

    if not settings.yandex_wordstat_token or not settings.yandex_cloud_folder_id:
        logger.warning("источник частотностей включён, но ключ или каталог не заданы")
        return NullSource()

    return YandexWordstat(settings.yandex_wordstat_token, settings.yandex_cloud_folder_id)
