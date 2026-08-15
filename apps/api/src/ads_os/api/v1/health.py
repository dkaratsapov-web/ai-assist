"""Проверка состояния сервиса."""

from __future__ import annotations

from fastapi import APIRouter

from ..deps import SettingsDep
from ..schemas import HealthResponse

router = APIRouter(tags=["service"])


@router.get("/health", response_model=HealthResponse, summary="Состояние сервиса")
async def health(settings: SettingsDep) -> HealthResponse:
    """Возвращает состояние и режим работы.

    Провайдер AI и адаптер площадки показаны намеренно: по ответу должно быть
    сразу видно, работает ли стенд на заглушках. Иначе легко принять
    сгенерированный заглушкой результат за вывод настоящей модели.
    """
    return HealthResponse(
        status="ok",
        app_env=settings.app_env,
        ai_provider=settings.ai_provider,
        ad_platform_adapter=settings.ad_platform_adapter,
    )
