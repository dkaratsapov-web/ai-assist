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
