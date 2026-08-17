"""Выбор рекламной площадки.

Одно место, где решается, с чем работает продукт: с заглушкой или с настоящим
Директом. Разбросанные по коду проверки настройки рано или поздно разойдутся, и
одна из них однажды окажется боевой там, где этого не ждали.

Здесь же стоит предохранитель, о котором договорились в v0.4 §2.1: боевой
адаптер не выдаётся, пока не пройдены проверки безопасности (v0.3 §114), даже
если токен уже лежит в настройках. Отдельный флаг для этого нужен именно
потому, что «переключить адаптер» и «разрешить трогать чужие деньги» — разные
решения, и принимать их одним движением нельзя.
"""

from __future__ import annotations

import logging

from ...config import Settings, get_settings
from .contracts import (
    AdPlatform,
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
from .mock import MockAdapter
from .yandex_direct import YandexDirectAdapter

logger = logging.getLogger(__name__)

__all__ = [
    "AdPlatform",
    "AdPlatformError",
    "Advertiser",
    "AuthError",
    "Campaign",
    "CampaignState",
    "DailyStats",
    "MockAdapter",
    "NotClearedForLiveError",
    "PlatformResponse",
    "QuotaError",
    "Usage",
    "YandexDirectAdapter",
    "get_ad_platform",
]


class NotClearedForLiveError(AdPlatformError):
    """Боевой доступ запрошен раньше, чем разрешён.

    Не ошибка настройки, а сработавший предохранитель: кто-то переключил
    адаптер, не пройдя проверки безопасности.
    """


def get_ad_platform(settings: Settings | None = None) -> AdPlatform:
    """Адаптер площадки по текущим настройкам.

    По умолчанию — заглушка. Боевой адаптер требует одновременно трёх вещей:
    выбранного адаптера, токена и снятого предохранителя. Любого одного мало.
    """
    settings = settings or get_settings()

    if settings.ad_platform_adapter != "yandex_direct":
        return MockAdapter()

    if not settings.ad_platform_live_approved:
        raise NotClearedForLiveError(
            "Боевой доступ к Директу не разрешён. Пройдите проверки безопасности "
            "и включите AD_PLATFORM_LIVE_APPROVED — переключения адаптера "
            "недостаточно."
        )

    if not settings.yandex_direct_token:
        raise AdPlatformError(
            "Выбран боевой адаптер Директа, но токен не задан. "
            "Положите его в YANDEX_DIRECT_TOKEN на сервере."
        )

    adapter = YandexDirectAdapter(
        token=settings.yandex_direct_token,
        login=settings.yandex_direct_login,
        sandbox=settings.yandex_direct_sandbox,
    )

    # Переход на настоящие деньги обязан быть заметен в журнале: это то
    # событие, которое потом ищут первым, когда что-то пошло не так.
    logger.warning(
        "рекламная площадка: боевой адаптер",
        extra={"sandbox": settings.yandex_direct_sandbox, "login": settings.yandex_direct_login},
    )
    return adapter
