"""Учёт квоты Вордстата.

Сто запросов в час — на весь сервис, а не на проект. Ошибка в этом счётчике
стоит не замедления, а отказа площадки на середине сбора, поэтому проверяется
именно поведение на границе и после неё.
"""

from __future__ import annotations

from datetime import UTC, datetime

from ads_os.services.wordstat_quota import (
    SAFE_PER_HOUR,
    MemoryQuota,
    seconds_until_reset,
)


class TestСчёт:
    async def test_первый_запрос_разрешён(self) -> None:
        assert await MemoryQuota().take() is True

    async def test_запросы_кончаются_на_пределе(self) -> None:
        quota = MemoryQuota(limit=3)

        assert [await quota.take() for _ in range(4)] == [True, True, True, False]

    async def test_остаток_виден(self) -> None:
        """Человеку нужно не «квота исчерпана», а сколько ещё можно."""
        quota = MemoryQuota(limit=10)
        for _ in range(4):
            await quota.take()

        assert await quota.remaining() == 6

    async def test_остаток_не_уходит_в_минус(self) -> None:
        quota = MemoryQuota(limit=2)
        for _ in range(5):
            await quota.take()

        assert await quota.remaining() == 0


class TestОкно:
    async def test_смена_часа_обнуляет_счёт(self) -> None:
        quota = MemoryQuota(limit=1)
        await quota.take()
        # Так выглядит наступивший новый час: окно в счётчике осталось старым.
        quota._window = "1970010100"

        assert await quota.take() is True

    def test_время_до_обновления_считается_от_начала_часа(self) -> None:
        moment = datetime(2026, 8, 18, 14, 30, 0, tzinfo=UTC)

        assert seconds_until_reset(moment) == 1800

    def test_в_начале_часа_ждать_почти_час(self) -> None:
        moment = datetime(2026, 8, 18, 14, 0, 0, tzinfo=UTC)

        assert seconds_until_reset(moment) == 3600


def test_предел_взят_с_запасом_от_ста() -> None:
    """Наши границы часа не совпадают с границами площадки, и упереться в её
    отказ вместо своего предела означало бы 429 на середине сбора."""
    assert SAFE_PER_HOUR < 100
