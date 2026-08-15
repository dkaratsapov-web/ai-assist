# ADS OS

Мультиканальная операционная система для специалиста по контекстной рекламе.
Основная платформа — Яндекс Директ, аналитика — Яндекс Метрика.
Каналы: Web (основной интерфейс), Telegram и MAX (интерфейс помощника).

## Документы

Порядок приоритета при конфликтах (ADS OS v0.4 Addendum §26):

1. `ADS OS v0.4 Architecture Hardening Addendum`
2. `ADS OS Master ТЗ v0.3`
3. Визуальные референсы / макеты
4. Реализационные предпочтения

Зафиксированные решения — в [`docs/architecture/v0.4-decisions.md`](docs/architecture/v0.4-decisions.md).
Дизайн-система — в [`docs/design-system.md`](docs/design-system.md).

## Структура

```
apps/
  web/          Next.js — основной интерфейс (Control Plane)
  api/          FastAPI — backend (пока не наполнен)
packages/
  tokens/       design-tokens.json — единый источник визуальных параметров (v0.4 §19)
  ui/           переиспользуемая библиотека компонентов (v0.4 §22)
  shared/       общие утилиты и типы
  schemas/      сгенерированные из OpenAPI TypeScript-типы (v0.4 §18)
services/
  ai/           AI-слой: провайдеры, structured output, валидация
  crawler/      изолированный краулер с SSRF-контролем (v0.4 §20)
  integrations/ AdPlatformAdapter, Metrica, Wordstat, CRM
  analytics/    аналитический слой, изолирован для возможного выноса (v0.4 §12)
workers/        фоновые задания (Celery)
docs/
  architecture/ ADR, ERD, границы API, фоновые задания
  adr/          Architecture Decision Records
  api/          контракты API
  product/      продуктовые спецификации
  security/     threat model, security test plan
infra/          окружения, деплой, CI
```

На текущем этапе наполнены `packages/tokens`, `packages/ui`, `apps/web` и `docs` —
это первый срез «UI-каркас и дизайн-система». Остальные директории зафиксированы
структурно и наполняются в следующих срезах.

## Требования

- Node.js >= 22
- pnpm >= 10

## Запуск

```bash
pnpm install
cp .env.example .env
pnpm dev            # http://localhost:3000
```

Полезные команды:

```bash
pnpm tokens             # пересобрать design tokens из design-tokens.json
pnpm build              # production-сборка web
pnpm typecheck          # проверка типов по всем пакетам
pnpm lint               # линтеры
pnpm storybook          # изолированный превью компонентов
```

## Дизайн-токены

`packages/tokens/design-tokens.json` — единственный источник правды для визуальных
параметров. Из него генерируются CSS-переменные для Web и константы для сообщений
ботов. Правка цветов, отступов, радиусов и таймингов делается **только** в этом
файле, а не в компонентах (v0.3 §141, v0.4 §19).

```
design-tokens.json → tokens.css (CSS variables / Tailwind @theme)
                   → tokens.ts  (константы для Web и bot message constants)
```

## Секреты

Секреты никогда не попадают в git, фронтенд-бандлы и логи (v0.3 §59, §94).
Локальная конфигурация — `.env` на основе `.env.example`. Production-секреты —
в Secret Manager / Vault / KMS.

Production-токены рекламных кабинетов запрещены до прохождения Security Acceptance
Criteria (v0.3 §114, v0.4 §2.1). До этого используются mock-адаптеры.
