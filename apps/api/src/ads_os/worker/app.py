"""Очередь фоновых задач.

Долгие операции не выполняются внутри HTTP-запроса (v0.3 §6, §79): краулер
может отвечать десятки секунд, и держать всё это время соединение — верный
способ положить сервис на нескольких одновременных запусках.

Разделение по очередям не косметическое. Краулер ходит по чужим сайтам и
запускается в отдельном воркере со своими правилами исходящего трафика
(v0.4 §20) — для этого его задачи должны попадать в собственную очередь.
"""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from ..config import get_settings

settings = get_settings()

celery_app = Celery("ads_os", broker=settings.redis_url, backend=settings.redis_url)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # Задача забирается только тогда, когда воркер готов её выполнять: иначе
    # при перезапуске воркера часть заданий теряется молча.
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # Повторы ограничены: бесконечно долбиться в неотвечающий сайт бессмысленно
    # и расходует воркер (v0.3 §105).
    task_default_retry_delay=30,
    task_max_retries=3,
    result_expires=3600,
    # Маршруты перечислены по одной задаче, а не маской. Маска на модуль отправила
    # бы в очередь краулера и разбор страницы — то есть задачу, которой нужна
    # база. Смысл разделения тогда пропал бы: процесс с доступом наружу получил
    # бы и доступ к данным клиентов.
    task_routes={
        "ads_os.worker.tasks.audit.fetch_site_page": {"queue": "crawler"},
        "ads_os.worker.tasks.audit.process_site_audit": {"queue": "default"},
        "ads_os.worker.tasks.competitors.process_competitor": {"queue": "default"},
        # Планировщик читает базу, поэтому идёт в обычную очередь, а не в
        # очередь краулера — у того доступа к базе нет и быть не должно.
        "ads_os.worker.tasks.schedule.recheck_sites": {"queue": "default"},
    },
    task_default_queue="default",
)

#: Модули задач перечислены явно.
#:
#: Здесь стоял autodiscover_tasks(["ads_os.worker.tasks"]) — и он не работал:
#: автопоиск принимает список *пакетов* и ищет в каждом подмодуль `tasks`,
#: то есть искал `ads_os.worker.tasks.tasks`. В результате воркер поднимался
#: без единой зарегистрированной задачи и молча выбрасывал всё, что приходило
#: в очередь, а аудит навсегда оставался в статусе «в очереди».
#:
#: Список проверяется тестом: добавить задачу и забыть строку здесь — ровно тот
#: же тихий отказ.
TASK_MODULES = (
    "ads_os.worker.tasks.audit",
    "ads_os.worker.tasks.competitors",
    "ads_os.worker.tasks.schedule",
)

celery_app.conf.imports = TASK_MODULES

#: Расписание регулярных задач.
#:
#: Запускается ежедневно, но сама задача решает, каким проектам действительно
#: пора: интервал проверки живёт рядом с ней, а не здесь. Ежедневный запуск при
#: недельном интервале означает, что проверки размазываются по дням, а не
#: сваливаются все разом в один.
#:
#: Час выбран ночной по московскому времени: краулер ходит по сайтам клиентов, и
#: делать это в рабочее время — значит попадать на пик их собственного трафика.
celery_app.conf.beat_schedule = {
    "recheck-sites": {
        "task": "ads_os.worker.tasks.schedule.recheck_sites",
        "schedule": crontab(hour=1, minute=30),
    },
}
