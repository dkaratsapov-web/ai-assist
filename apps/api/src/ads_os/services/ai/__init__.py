"""Слой AI.

Провайдер не выбран: система работает на детерминированной заглушке, а реальный
провайдер подключается конфигурацией. Требование v0.3 §98 — иметь возможность
отключить конкретного провайдера — здесь выполняется буквально: имя провайдера
не встречается ни в одном модуле бизнес-логики.
"""

from collections.abc import Callable

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
from .provider import AiProvider, ProviderRegistry, build_prompt
from .stub import StubProvider

__all__ = [
    "AiProvider",
    "AiProviderError",
    "AiRequest",
    "AiResult",
    "AiTask",
    "AiUsage",
    "ProviderRegistry",
    "SensitiveDataNotAllowedError",
    "Sensitivity",
    "StubProvider",
    "UntrustedContent",
    "build_prompt",
    "build_registry",
    "parse_routes",
]


def build_registry() -> ProviderRegistry:
    """Собирает реестр провайдеров по настройкам.

    Пока настроена только заглушка. Добавление реального провайдера — новая
    ветка в этой функции и переменная окружения, без изменений в вызывающих
    модулях.
    """
    from ...config import get_settings

    settings = get_settings()

    default = _make(settings.ai_provider)

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
        by_task=parse_routes(settings.ai_provider_by_task),
    )


#: Известные провайдеры. Пока подключена только заглушка: выбор моделей —
#: открытое решение владельца продукта (v0.4 §25). Каждый новый провайдер
#: добавляется одной строкой здесь и не затрагивает ни один вызывающий модуль.
_PROVIDERS: dict[str, Callable[[], AiProvider]] = {"stub": StubProvider}


def _make(name: str) -> AiProvider:
    factory = _PROVIDERS.get(name)
    if factory is None:
        raise NotImplementedError(
            f"Провайдер {name!r} ещё не подключён. Доступны: "
            f"{', '.join(sorted(_PROVIDERS))}."
        )
    return factory()


def parse_routes(raw: str) -> dict[AiTask, AiProvider]:
    """Разбирает маршруты вида «задача=провайдер» через запятую.

    Ошибка в настройке роняет запуск, а не молча уводит задачу к провайдеру по
    умолчанию. Тихая подмена здесь означала бы, что данные ушли не той модели,
    которой их разрешили отправлять, — и заметить это было бы нечем.
    """
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

        routes[task] = _make(provider_name.strip())

    return routes
