"""Состояние подключения к рекламной площадке.

Один запрос, который отвечает на вопрос «работает ли доступ» — тот самый,
который задают первым, когда токен наконец получен, и тот, к которому
возвращаются, когда что-то перестало работать.

Пробный запрос делается настоящий: список доступных рекламодателей. Проверять
доступ по наличию токена в настройках бессмысленно — токен бывает истёкшим,
отозванным или выпущенным не на то приложение, и все три случая выглядят
одинаково, пока не спросишь площадку.
"""

from __future__ import annotations

from fastapi import APIRouter

from ...config import get_settings
from ...services.ad_platform import AdPlatformError, get_ad_platform
from ..deps import TenantDep
from ..schemas import AdPlatformAdvertiserRead, AdPlatformStatusRead

router = APIRouter(tags=["ad-platform"])


@router.get(
    "/ad-platform/status",
    response_model=AdPlatformStatusRead,
    summary="Состояние подключения к Директу",
)
async def get_status(ctx: TenantDep) -> AdPlatformStatusRead:
    """Проверяет доступ и возвращает остаток баллов API."""
    settings = get_settings()

    try:
        platform = get_ad_platform(settings)
    except AdPlatformError as exc:
        # Предохранитель и отсутствие токена — не сбой сервера, а состояние
        # настройки. Отдаём его как ответ, а не как ошибку: экран должен
        # показать причину, а не пустоту с кодом 500.
        return AdPlatformStatusRead(
            adapter=settings.ad_platform_adapter,
            is_live=False,
            live_approved=settings.ad_platform_live_approved,
            connected=False,
            error=exc.message,
        )

    try:
        result = await platform.advertisers()
    except AdPlatformError as exc:
        return AdPlatformStatusRead(
            adapter=platform.name,
            is_live=platform.is_live,
            live_approved=settings.ad_platform_live_approved,
            connected=False,
            error=exc.message,
        )

    return AdPlatformStatusRead(
        adapter=platform.name,
        is_live=platform.is_live,
        live_approved=settings.ad_platform_live_approved,
        connected=True,
        advertisers=[
            AdPlatformAdvertiserRead(
                login=item.login,
                name=item.name,
                currency=item.currency,
                can_edit=item.can_edit,
            )
            for item in result.advertisers
        ],
        units_spent=result.usage.spent,
        units_rest=result.usage.rest,
        units_limit=result.usage.limit,
        units_low=result.usage.is_low,
    )
