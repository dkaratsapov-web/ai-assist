"""Конфигурация приложения.

Все настройки приходят из окружения. Секреты в коде и в репозитории не
появляются никогда (v0.3 §59, §94) — образец переменных лежит в `.env.example`.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

AppEnv = Literal["development", "staging", "production"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: AppEnv = "development"
    app_base_url: str = "http://localhost:3000"
    log_level: str = "info"

    database_url: str = "postgresql+asyncpg://ads_os@127.0.0.1:5433/ads_os"
    database_echo: bool = False

    redis_url: str = "redis://localhost:6379/0"

    # Провайдер AI не выбран: разработка идёт на детерминированной заглушке,
    # конкретный провайдер подключается конфигурацией (v0.3 §98).
    ai_provider: str = "stub"
    # Для чувствительных данных внешний провайдер запрещён по умолчанию
    # (v0.4 §2.3). Ослабляется только явным решением по обработке ПДн.
    ai_sensitive_provider: str = "none"

    # До прохождения Security Acceptance Criteria (v0.3 §114) работа с рекламной
    # площадкой идёт только через заглушку, даже если токен уже получен
    # (v0.4 §2.1).
    ad_platform_adapter: Literal["mock", "yandex_direct"] = "mock"

    autopilot_enabled: bool = Field(
        default=False,
        description="Глобальный выключатель автопилота. По умолчанию выключен (v0.4 §10).",
    )

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    """Настройки читаются один раз за процесс."""
    return Settings()
