# packages/schemas

TypeScript-типы и клиент, **генерируемые** из OpenAPI (v0.4 §18).

Правило: вручную дублирующиеся Python/TS DTO не поддерживаются. Источник правды —
Pydantic-схемы в `apps/api`. Codegen запускается в CI и проверяет drift.

Наполняется вместе с первыми endpoint-ами backend.
