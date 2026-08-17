# Frontend ADS OS.
#
# Собирается из корня репозитория: приложение зависит от пакетов воркспейса
# (@ads-os/ui, @ads-os/tokens, @ads-os/schemas), и без них сборка невозможна.
#
# Контекст сборки: корень репозитория.
#   docker build -f apps/web/Dockerfile .

FROM node:22-slim AS builder

ENV PNPM_HOME=/pnpm \
    PATH=/pnpm:$PATH \
    NEXT_TELEMETRY_DISABLED=1

RUN corepack enable

WORKDIR /build

# Сначала только манифесты — слой с зависимостями переиспользуется, пока они
# не менялись.
COPY pnpm-workspace.yaml pnpm-lock.yaml package.json ./
COPY apps/web/package.json ./apps/web/
COPY packages/tokens/package.json ./packages/tokens/
COPY packages/ui/package.json ./packages/ui/
COPY packages/schemas/package.json ./packages/schemas/

RUN pnpm install --frozen-lockfile

COPY tsconfig.base.json ./
COPY packages ./packages
COPY apps/web ./apps/web

# Значения NEXT_PUBLIC_* попадают в браузерный бандл на этапе сборки, поэтому
# передаются аргументами. Секретов среди них нет и быть не должно.
# Пустое значение означает относительные пути: браузер обращается к тому же
# домену, запросы проксирует Caddy.
ARG NEXT_PUBLIC_API_URL=""
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL

RUN pnpm --filter @ads-os/tokens build \
    && pnpm --filter @ads-os/web build

# Next обходит зависимости статически и копирует в самодостаточную сборку
# только те файлы, до которых дотянулся. До ESM-части @swc/helpers он не
# дотягивается: её подключает внутренний загрузчик самого Next уже во время
# работы. В образ попадает половина пакета — есть cjs, нет esm, — и контейнер
# падает при старте с «Cannot find module .../esm/_interop_require_default.js».
#
# Досылаем пакет целиком. Версия не зашита: она меняется вместе с Next, и
# зашитая однажды превратилась бы в поломку при следующем обновлении.
RUN set -eu; \
    src="$(ls -d node_modules/.pnpm/@swc+helpers@*/node_modules/@swc/helpers 2>/dev/null | head -1)"; \
    dst="$(ls -d apps/web/.next/standalone/node_modules/.pnpm/@swc+helpers@*/node_modules/@swc/helpers 2>/dev/null | head -1)"; \
    if [ -n "$src" ] && [ -n "$dst" ]; then \
        cp -r "$src/." "$dst/"; \
        echo "@swc/helpers дослан целиком"; \
    else \
        echo "@swc/helpers не нуждается в досылке"; \
    fi; \
    test -f apps/web/.next/standalone/apps/web/server.js


FROM node:22-slim AS runtime

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000

# Контейнер не запускается под root (v0.3 §108). Пользователь node уже есть в
# базовом образе.
WORKDIR /app

COPY --from=builder --chown=node:node /build/apps/web/.next/standalone ./
COPY --from=builder --chown=node:node /build/apps/web/.next/static ./apps/web/.next/static
COPY --from=builder --chown=node:node /build/apps/web/public ./apps/web/public

USER node

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD node -e "fetch('http://127.0.0.1:3000/').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

CMD ["node", "apps/web/server.js"]
