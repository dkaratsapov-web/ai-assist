"""Разделение очередей — это граница безопасности, а не настройка удобства.

Воркер краулера ходит по чужим сайтам и потому запускается без доступа к базе
(v0.3 §97, v0.4 §20). Держится это на маршрутизации задач: если разбор страницы
случайно уедет в очередь краулера, он попадёт в процесс, у которого есть выход
в интернет — и там же окажется доступ к данным всех клиентов.

Поэтому маршруты проверяются тестом, а не только глазами при чтении конфига.
"""

from __future__ import annotations

import importlib

from ads_os.worker.app import TASK_MODULES, celery_app

CRAWLER_QUEUE = "crawler"
DEFAULT_QUEUE = "default"


def route(task_name: str) -> str:
    """Очередь, в которую Celery отправит задачу по текущим настройкам."""
    routes = celery_app.conf.task_routes or {}
    destination = routes.get(task_name)
    if destination is None:
        return str(celery_app.conf.task_default_queue)
    return str(destination["queue"])


class TestМаршрутыЗадач:
    def test_загрузка_страницы_идёт_в_очередь_краулера(self) -> None:
        assert route("ads_os.worker.tasks.audit.fetch_site_page") == CRAWLER_QUEUE

    def test_разбор_страницы_не_идёт_в_очередь_краулера(self) -> None:
        """Разбору нужна база, а у воркера краулера базы нет."""
        assert route("ads_os.worker.tasks.audit.process_site_audit") == DEFAULT_QUEUE

    def test_разбор_конкурента_не_идёт_в_очередь_краулера(self) -> None:
        assert route("ads_os.worker.tasks.competitors.process_competitor") == DEFAULT_QUEUE

    def test_в_очередь_краулера_попадают_только_разрешённые_задачи(self) -> None:
        """Список задач краулера закрытый.

        Проверка ловит ровно один сценарий: кто-то добавил задачу с доступом к
        базе и по привычке отправил её в очередь краулера.
        """
        crawler_tasks = {
            name
            for name, destination in (celery_app.conf.task_routes or {}).items()
            if destination["queue"] == CRAWLER_QUEUE
        }
        assert crawler_tasks == {"ads_os.worker.tasks.audit.fetch_site_page"}


class TestРегистрацияЗадач:
    """Задача, не зарегистрированная в воркере, отбрасывается молча.

    Именно это и происходило: вместо перечисления модулей стоял автопоиск,
    который искал подмодуль `tasks` внутри пакета `ads_os.worker.tasks` — то
    есть `ads_os.worker.tasks.tasks`. Воркер поднимался пустым, сообщения из
    очереди выбрасывались, а аудит навсегда оставался «в очереди».
    """

    def test_все_модули_задач_импортируются(self) -> None:
        for module in TASK_MODULES:
            importlib.import_module(module)

    def test_каждая_задача_из_маршрутов_зарегистрирована(self) -> None:
        for module in TASK_MODULES:
            importlib.import_module(module)

        for name in celery_app.conf.task_routes or {}:
            assert name in celery_app.tasks, f"задача {name} не зарегистрирована"

    def test_модули_задач_перечислены_в_настройках(self) -> None:
        """Воркер импортирует именно этот список при старте."""
        assert tuple(celery_app.conf.imports) == TASK_MODULES


class TestНастройкиОчереди:
    def test_задача_подтверждается_после_выполнения(self) -> None:
        """Иначе при перезапуске воркера часть аудитов пропала бы молча."""
        assert celery_app.conf.task_acks_late is True

    def test_повторы_ограничены(self) -> None:
        """Неотвечающий сайт не должен занимать воркер бесконечно (v0.3 §105)."""
        assert celery_app.conf.task_max_retries == 3
