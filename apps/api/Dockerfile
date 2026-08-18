# Backend ADS OS.
#
# Требования v0.3 §108: минимальный базовый образ, контейнер не запускается под
# root, отладочные точки в production отключены (за это отвечает APP_ENV).

FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# Зависимости ставятся отдельным слоем: правка кода не приводит к их
# переустановке при каждой сборке.
#
# Пустой пакет-заглушка нужен, чтобы сборка метаданных вообще состоялась:
# pyproject объявляет пакеты в каталоге src, и без него `pip install .` падает
# на «Getting requirements to build wheel». Настоящий код копируется следующим
# слоем и ставится поверх без переустановки зависимостей.
COPY pyproject.toml ./
RUN mkdir -p src/ads_os && touch src/ads_os/__init__.py \
    && python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install .

COPY src ./src
RUN /opt/venv/bin/pip install --no-deps .


FROM python:3.11-slim AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Отдельный непривилегированный пользователь: контейнер под root не запускается.
RUN groupadd --system --gid 1001 adsos \
    && useradd --system --uid 1001 --gid adsos --create-home adsos

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --chown=adsos:adsos alembic.ini ./
COPY --chown=adsos:adsos alembic ./alembic
COPY --chown=adsos:adsos scripts ./scripts
COPY --chown=adsos:adsos src ./src

USER adsos

EXPOSE 8000

# Проверка живости: оркестратор не должен считать сервис готовым до того, как
# приложение действительно отвечает.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "ads_os.main:app", "--host", "0.0.0.0", "--port", "8000", "--app-dir", "src"]


# Образ краулера: то же приложение плюс браузер.
#
# Отдельной ступенью, а не в общем образе, потому что браузер весит сотни
# мегабайт. В образах API, обычного воркера и миграций он не нужен ни разу, и
# платить за него местом на диске и временем выкладки при каждом обновлении
# незачем.
#
# Браузер берётся из пакетов системы, а не скачивается Playwright: так он
# обновляется вместе с системой, а образ не тянет вторую копию зависимостей.
FROM runtime AS crawler

USER root

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        chromium \
        fonts-liberation \
        fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

RUN /opt/venv/bin/pip install --no-cache-dir "playwright>=1.49"

# Playwright по умолчанию ищет собственную скачанную сборку. Указываем
# системную: без этого он при первом запуске полезет в интернет за браузером —
# из воркера краулера, которому в сеть можно только к проверяемым сайтам.
ENV ADS_OS_CHROMIUM=/usr/bin/chromium \
    PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1

USER adsos
