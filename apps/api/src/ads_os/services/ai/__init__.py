"""Слой AI.

Провайдер не выбран: система работает на детерминированной заглушке, а реальный
провайдер подключается конфигурацией. Требование v0.3 §98 — иметь возможность
отключить конкретного провайдера — здесь выполняется буквально: имя провайдера
не встречается ни в одном модуле бизнес-логики.
"""

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
]


def build_registry() -> ProviderRegistry:
    """Собирает реестр провайдеров по настройкам.

    Пока настроена только заглушка. Добавление реального провайдера — новая
    ветка в этой функции и переменная окружения, без изменений в вызывающих
    модулях.
    """
    from ...config import get_settings

    settings = get_settings()

    if settings.ai_provider == "stub":
        default: AiProvider = StubProvider()
    else:
        raise NotImplementedError(
            f"Провайдер {settings.ai_provider!r} ещё не подключён. "
            "Выбор провайдера — открытое решение владельца продукта (v0.4 §25)."
        )

    # Для чувствительных данных провайдера нет по умолчанию: попытка отправить
    # персональные данные наружу должна падать, а не тихо проходить (v0.4 §2.3).
    sensitive: AiProvider | None = None
    if settings.ai_sensitive_provider != "none":
        raise NotImplementedError(
            "Обработка чувствительных данных внешним провайдером требует решения "
            "по обработке персональных данных (v0.4 §2.3)."
        )

    return ProviderRegistry(default=default, sensitive=sensitive)
