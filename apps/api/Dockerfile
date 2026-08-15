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
