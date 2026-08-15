# apps/api

FastAPI backend. Наполняется в срезе «Фундамент платформы» (MVP 0):
Auth/MFA, Organizations, RBAC/tenant scope, Projects, Project Data Core,
миграции, очередь, Audit Log.

Pydantic-схемы здесь — источник правды для контракта API. OpenAPI генерируется
FastAPI, TypeScript-типы генерируются в `packages/schemas` (v0.4 §18).
