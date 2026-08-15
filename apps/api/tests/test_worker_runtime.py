"""Повторный запуск задач в одном процессе воркера.

Тест синхронный и намеренно вызывает задачи так, как их вызывает Celery: два
раза подряд в одном процессе. Первый вызов проходил всегда — ломался второй,
потому что пул соединений оставался привязан к уже закрытому циклу событий.
На стенде это выглядело бы как случайный отказ каждой второй проверки.
"""

from __future__ import annotations

import uuid

from ads_os.worker.tasks.audit import process_site_audit
from ads_os.worker.tasks.competitors import process_competitor

FETCH_FAILED = {"ok": False, "reason": "сервер не ответил вовремя"}


class TestПовторныйЗапуск:
    def test_аудит_дважды_подряд(self) -> None:
        first = process_site_audit(FETCH_FAILED, str(uuid.uuid4()))
        second = process_site_audit(FETCH_FAILED, str(uuid.uuid4()))

        assert first == "not_found"
        assert second == "not_found"

    def test_конкурент_дважды_подряд(self) -> None:
        first = process_competitor(FETCH_FAILED, str(uuid.uuid4()))
        second = process_competitor(FETCH_FAILED, str(uuid.uuid4()))

        assert first == "not_found"
        assert second == "not_found"

    def test_разные_задачи_подряд(self) -> None:
        """Пул общий на процесс, поэтому чередование задач тоже проверяется."""
        assert process_site_audit(FETCH_FAILED, str(uuid.uuid4())) == "not_found"
        assert process_competitor(FETCH_FAILED, str(uuid.uuid4())) == "not_found"
        assert process_site_audit(FETCH_FAILED, str(uuid.uuid4())) == "not_found"
