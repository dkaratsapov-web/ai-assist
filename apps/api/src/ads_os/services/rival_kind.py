"""Кто это на самом деле: конкурент, площадка или статья.

Специалист берёт адреса из поисковой выдачи и добавляет их в конкуренты. В
выдаче рядом с настоящими конкурентами стоят Авито, 2ГИС, Озон, «Дзен» и
подборка «10 лучших компаний города». Внешне это такие же сайты, и разбор у них
проходит так же — только сравнивать с ними посадочную страницу клиента
бессмысленно. У Авито всегда есть форма, всегда есть цены и всегда есть отзывы;
из того, что у клиента этого нет, не следует ровным счётом ничего.

Разделение идёт в два шага, и первый — не модель.

**Известные площадки узнаются по адресу.** Авито остаётся Авито независимо от
того, что написано на странице. Это точно, бесплатно и не зависит ни от чьей
доступности. Список ведётся вручную и покрывает то, что реально попадается в
русской выдаче.

**Всё остальное разбирает модель.** Незнакомый домен может оказаться и
конкурентом, и отраслевым каталогом, и блогом производителя. Отличить их можно
только по содержимому страницы, и здесь суждение действительно нужно.

Чего модель здесь не делает: не ищет конкурентов и не придумывает названий. Она
получает страницу, которую нашёл человек и загрузил краулер, и отвечает на один
вопрос — что это такое. Список остаётся ровно тем, который собрал человек.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from .ai import (
    AiProviderError,
    AiRequest,
    AiTask,
    ProviderRegistry,
    Sensitivity,
    UntrustedContent,
)

logger = logging.getLogger(__name__)

MAX_TEXT_CHARS = 6000


class Kind(StrEnum):
    """Что за сайт."""

    #: Компания, которая сама оказывает услугу или продаёт товар. С ней и
    #: сравниваемся.
    COMPETITOR = "competitor"
    #: Площадка с объявлениями чужих исполнителей: Авито, Профи, Услуги.
    AGGREGATOR = "aggregator"
    #: Справочник организаций с карточками и отзывами: 2ГИС, Зун, Яндекс Карты.
    DIRECTORY = "directory"
    #: Маркетплейс: Озон, Вайлдберриз, Мегамаркет.
    MARKETPLACE = "marketplace"
    #: Статья, обзор, подборка «10 лучших» — контентная страница.
    ARTICLE = "article"
    #: Производитель или бренд: продаёт через дилеров, а не конечному клиенту.
    MANUFACTURER = "manufacturer"
    #: Опознать не удалось.
    OTHER = "other"


KIND_LABELS: dict[Kind, str] = {
    Kind.COMPETITOR: "Конкурент",
    Kind.AGGREGATOR: "Площадка объявлений",
    Kind.DIRECTORY: "Справочник",
    Kind.MARKETPLACE: "Маркетплейс",
    Kind.ARTICLE: "Статья",
    Kind.MANUFACTURER: "Производитель",
    Kind.OTHER: "Не опознан",
}

#: С кем сравнение имеет смысл. У площадки всегда есть форма, цены и отзывы —
#: и из того, что у клиента их нет, ничего не следует.
COMPARABLE = frozenset({Kind.COMPETITOR, Kind.MANUFACTURER})

KIND_HINTS: dict[Kind, str] = {
    Kind.COMPETITOR: "Прямой конкурент: сравнение условий имеет смысл.",
    Kind.AGGREGATOR: (
        "Это площадка с объявлениями других исполнителей, а не компания. Сравнивать "
        "с ней посадочную нельзя: форма, цены и отзывы там есть всегда. Но в аукционе "
        "она участвует и цену клика поднимает — это стоит учесть в бюджете."
    ),
    Kind.DIRECTORY: (
        "Справочник организаций. Сравнивать не с чем: карточки заполняют сами "
        "компании. Зато полезно проверить, есть ли там карточка клиента."
    ),
    Kind.MARKETPLACE: (
        "Маркетплейс. Он играет по своим правилам — доставкой, отзывами и ценой "
        "витрины. Сравнение посадочных здесь ничего не даст."
    ),
    Kind.ARTICLE: (
        "Это статья или подборка, а не компания. В аукционе она обычно не "
        "участвует. Полезна другим: по ней видно, какие возражения у покупателя."
    ),
    Kind.MANUFACTURER: (
        "Производитель или бренд. Сравниваться можно, но помните: он продаёт "
        "через дилеров и цену держит другую."
    ),
    Kind.OTHER: "Что это за сайт, определить не удалось. Решайте сами.",
}


class KindVerdict(BaseModel):
    """Ответ модели."""

    kind: Kind
    reason: str = Field(description="Почему именно так. Одно предложение.")
    #: Продаёт ли сайт сам или сводит с чужими исполнителями. Главный
    #: разделитель между конкурентом и площадкой.
    sells_directly: bool


class Source(StrEnum):
    """Откуда взялся вывод. Без этого его нельзя взвесить."""

    #: Известный домен: точно, бесплатно и ни от чего не зависит.
    KNOWN = "known"
    #: Разобрала модель.
    MODEL = "model"
    #: Определить не удалось.
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class KindResult:
    kind: Kind = Kind.OTHER
    reason: str = ""
    source: Source = Source.UNKNOWN
    confidence: float = 0.0
    tokens: int = 0

    @property
    def comparable(self) -> bool:
        return self.kind in COMPARABLE

    def as_stored(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "label": KIND_LABELS[self.kind],
            "reason": self.reason,
            "hint": KIND_HINTS[self.kind],
            "comparable": self.comparable,
            "source": self.source.value,
            "confidence": self.confidence,
        }


#: Домены, которые узнаются без модели. Список ведётся руками намеренно: это
#: не догадка, а знание — Авито остаётся Авито, что бы ни было на странице.
KNOWN_DOMAINS: dict[str, Kind] = {
    "avito.ru": Kind.AGGREGATOR,
    "youla.ru": Kind.AGGREGATOR,
    "profi.ru": Kind.AGGREGATOR,
    "uslugi.yandex.ru": Kind.AGGREGATOR,
    "yandex.ru": Kind.AGGREGATOR,
    "workspace.ru": Kind.AGGREGATOR,
    "remontnik.ru": Kind.AGGREGATOR,
    "youdo.com": Kind.AGGREGATOR,
    "tiu.ru": Kind.AGGREGATOR,
    "pulscen.ru": Kind.AGGREGATOR,
    "blizko.ru": Kind.AGGREGATOR,
    "2gis.ru": Kind.DIRECTORY,
    "zoon.ru": Kind.DIRECTORY,
    "yell.ru": Kind.DIRECTORY,
    "flamp.ru": Kind.DIRECTORY,
    "orgpage.ru": Kind.DIRECTORY,
    "rusprofile.ru": Kind.DIRECTORY,
    "otzovik.com": Kind.DIRECTORY,
    "irecommend.ru": Kind.DIRECTORY,
    "ozon.ru": Kind.MARKETPLACE,
    "wildberries.ru": Kind.MARKETPLACE,
    "megamarket.ru": Kind.MARKETPLACE,
    "aliexpress.ru": Kind.MARKETPLACE,
    "market.yandex.ru": Kind.MARKETPLACE,
    "leroymerlin.ru": Kind.MARKETPLACE,
    "petrovich.ru": Kind.MARKETPLACE,
    "dzen.ru": Kind.ARTICLE,
    "vc.ru": Kind.ARTICLE,
    "habr.com": Kind.ARTICLE,
    "pikabu.ru": Kind.ARTICLE,
    "vk.com": Kind.ARTICLE,
    "ok.ru": Kind.ARTICLE,
    "t.me": Kind.ARTICLE,
    "youtube.com": Kind.ARTICLE,
    "wikipedia.org": Kind.ARTICLE,
}


def domain(url: str) -> str:
    """Домен без схемы, порта и www."""
    host = url.split("://")[-1].split("/")[0].split("?")[0].split(":")[0].lower()
    return host.removeprefix("www.")


def known(url: str) -> Kind | None:
    """Узнаёт площадку по адресу.

    Поддомены считаются тем же сайтом: `uslugi.yandex.ru` и `msk.avito.ru` —
    это те же площадки. Проверка идёт от полного имени к более короткому,
    чтобы `uslugi.yandex.ru` не был опознан просто как «Яндекс».
    """
    host = domain(url)
    parts = host.split(".")

    for start in range(len(parts) - 1):
        candidate = ".".join(parts[start:])
        if candidate in KNOWN_DOMAINS:
            return KNOWN_DOMAINS[candidate]

    return None


INSTRUCTION = """Определи, что за сайт перед тобой. Выбери ровно одно значение:

- competitor — компания, которая сама оказывает услугу или продаёт товар конечному покупателю.
- aggregator — площадка с объявлениями других исполнителей: заявка уходит не владельцу сайта.
- directory — справочник организаций: карточки компаний, адреса, отзывы.
- marketplace — витрина с товарами многих продавцов и корзиной.
- article — статья, обзор, подборка «лучших компаний», блог.
- manufacturer — производитель или бренд, который продаёт через дилеров, а не напрямую.
- other — ничего из перечисленного.

Главный разделитель — кому уходит заявка. Если посетитель оставляет её владельцу
сайта, это competitor. Если владелец сайта только сводит посетителя с чужими
исполнителями, это aggregator.

Отвечай по-русски. В поле reason — одно предложение о том, что на странице
показало ответ. Ничего не выдумывай: если на странице этого не видно, ставь
other."""


async def classify(
    url: str,
    text: str,
    *,
    title: str = "",
    registry: ProviderRegistry | None = None,
    organization_id: Any = None,
    project_id: Any = None,
) -> KindResult:
    """Определяет, что за сайт. Никогда не бросает исключений.

    Известный домен разбирается без модели: это не догадка, а знание, и платить
    за него незачем.
    """
    if (kind := known(url)) is not None:
        return KindResult(
            kind=kind,
            reason=f"{domain(url)} — известная площадка, опознана по адресу.",
            source=Source.KNOWN,
            confidence=1.0,
        )

    registry = registry or _registry()
    if registry is None:
        return KindResult(reason="Определение вида сайта не настроено.")

    # Заглушка отвечает валидно по схеме и выдуманно. Пометить конкурента
    # «площадкой» на этом основании значит испортить сравнение молча.
    if registry.resolve(AiTask.COMPETITOR_EXTRACTION, Sensitivity.SAFE_PUBLIC).name == "stub":
        return KindResult(reason="Определение вида сайта не подключено.")

    body = text.strip()[:MAX_TEXT_CHARS]
    if len(body) < 200:
        return KindResult(reason="На странице слишком мало текста, чтобы её опознать.")

    request: AiRequest[KindVerdict] = AiRequest(
        task=AiTask.COMPETITOR_EXTRACTION,
        sensitivity=Sensitivity.SAFE_PUBLIC,
        response_model=KindVerdict,
        instruction=f"{INSTRUCTION}\n\nАдрес: {domain(url)}\nЗаголовок: {title or 'нет'}",
        content=(UntrustedContent(source=domain(url), text=body, source_id=url),),
        organization_id=organization_id,
        project_id=project_id,
    )

    try:
        result = await registry.complete(request)
    except AiProviderError as error:
        logger.info("вид сайта не определён", extra={"reason": str(error)[:200]})
        return KindResult(reason="Определить вид сайта не удалось.")
    except Exception as error:
        logger.warning("определение вида сайта сорвалось", extra={"error": type(error).__name__})
        return KindResult(reason="Определить вид сайта не удалось.")

    verdict = result.payload
    return KindResult(
        # Ответ «конкурент» без прямой продажи противоречит сам себе. Верим
        # признаку, а не ярлыку: по нему и проходит настоящая граница.
        kind=Kind.AGGREGATOR
        if verdict.kind is Kind.COMPETITOR and not verdict.sells_directly
        else verdict.kind,
        reason=verdict.reason[:300],
        source=Source.MODEL,
        confidence=result.confidence,
        tokens=result.usage.total_tokens,
    )


def _registry() -> ProviderRegistry | None:
    from .ai import build_registry

    try:
        return build_registry()
    except Exception as error:
        logger.warning("провайдер модели не собран", extra={"error": type(error).__name__})
        return None
