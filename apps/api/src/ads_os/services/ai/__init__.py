"""Слой AI.

Провайдер выбирается настройкой. По умолчанию работает детерминированная
заглушка: она не ходит в сеть, ничего не стоит и даёт один и тот же ответ на
один и тот же запрос, поэтому на ней держатся тесты. Настоящая модель
включается одной переменной окружения.

Требование v0.3 §98 — иметь возможность отключить конкретного провайдера —
здесь выполняется буквально: имя провайдера не встречается ни в одном модуле
бизнес-логики. Вся его конкретика заканчивается в этом файле.
"""

from collections.abc import Callable
from typing import TYPE_CHECKING

from .contracts import (
    AiProviderError,
    AiRequest,
    AiResult,
    AiTask,
    AiUsage,
    SensitiveDataNotAllowedError,
    Sensitivity,
    UntrustedContent,
)
from .openai_provider import OpenAiProvider
from .provider import AiProvider, ProviderRegistry, build_prompt
from .stub import StubProvider

if TYPE_CHECKING:
    from ...config import Settings

__all__ = [
    "AiProvider",
    "AiProviderError",
    "AiRequest",
    "AiResult",
    "AiTask",
    "AiUsage",
    "OpenAiProvider",
    "ProviderRegistry",
    "SensitiveDataNotAllowedError",
    "Sensitivity",
    "StubProvider",
    "UntrustedContent",
    "build_prompt",
    "build_registry",
    "parse_routes",
]


def build_registry(settings: "Settings | None" = None) -> ProviderRegistry:
    """Собирает реестр провайдеров по настройкам.

    Добавление ещё одного провайдера — строка в таблице ниже и переменная
    окружения, без изменений в вызывающих модулях.
    """
    from ...config import get_settings

    settings = settings or get_settings()

    default = _make(settings.ai_provider, settings)

    # Для чувствительных данных провайдера нет по умолчанию: попытка отправить
    # персональные данные наружу должна падать, а не тихо проходить (v0.4 §2.3).
    sensitive: AiProvider | None = None
    if settings.ai_sensitive_provider != "none":
        raise NotImplementedError(
            "Обработка чувствительных данных внешним провайдером требует решения "
            "по обработке персональных данных (v0.4 §2.3)."
        )

    return ProviderRegistry(
        default=default,
        sensitive=sensitive,
        by_task=parse_routes(settings.ai_provider_by_task, settings),
    )


def _openai(settings: "Settings") -> AiProvider:
    """Провайдер OpenAI из настроек.

    Без ключа не собирается вовсе. Молча откатиться на заглушку было бы хуже
    всего: система продолжила бы работать, выдавая выдуманные заглушкой ответы
    за разбор модели, и заметить подмену было бы нечем.
    """
    if not settings.openai_api_key:
        raise ValueError(
            "Провайдер 'openai' включён, но ключ не задан. Укажите OPENAI_API_KEY "
            "или верните AI_PROVIDER=stub."
        )

    return OpenAiProvider(
        settings.openai_api_key,
        model=settings.openai_model,
        bulk_model=settings.openai_model_bulk,
        base_url=settings.openai_base_url,
    )


#: Известные провайдеры. Каждый новый добавляется одной строкой здесь и не
#: затрагивает ни один вызывающий модуль.
_PROVIDERS: dict[str, Callable[["Settings"], AiProvider]] = {
    "stub": lambda settings: StubProvider(),
    "openai": _openai,
}


def _make(name: str, settings: "Settings") -> AiProvider:
    factory = _PROVIDERS.get(name)
    if factory is None:
        raise NotImplementedError(
            f"Провайдер {name!r} ещё не подключён. Доступны: "
            f"{', '.join(sorted(_PROVIDERS))}."
        )
    return factory(settings)


def parse_routes(raw: str, settings: "Settings | None" = None) -> dict[AiTask, AiProvider]:
    """Разбирает маршруты вида «задача=провайдер» через запятую.

    Ошибка в настройке роняет запуск, а не молча уводит задачу к провайдеру по
    умолчанию. Тихая подмена здесь означала бы, что данные ушли не той модели,
    которой их разрешили отправлять, — и заметить это было бы нечем.
    """
    from ...config import get_settings

    settings = settings or get_settings()
    routes: dict[AiTask, AiProvider] = {}

    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue

        task_name, _, provider_name = chunk.partition("=")
        if not provider_name:
            raise ValueError(f"Маршрут {chunk!r} должен иметь вид «задача=провайдер»")

        try:
            task = AiTask(task_name.strip())
        except ValueError as exc:
            raise ValueError(
                f"Неизвестная задача {task_name.strip()!r}. Доступны: "
                f"{', '.join(t.value for t in AiTask)}."
            ) from exc

        routes[task] = _make(provider_name.strip(), settings)

    return routes
