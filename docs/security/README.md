# Security

Здесь живут threat model, security test plan (SEC-001…SEC-020) и Security
Acceptance Criteria.

Ключевое правило (v0.3 §118): безопасность — часть бизнес-логики, а не
инфраструктурное дополнение. Ни Web, ни Telegram, ни MAX, ни AI Agent не имеют
права обходить цепочку
UNTRUSTED INPUT → VALIDATION → IDENTITY → TENANT/RBAC → AI/BUSINESS LOGIC →
RECOMMENDATION → POLICY & SAFETY → APPROVAL → IDEMPOTENT EXECUTION → AUDIT →
MONITORING/ROLLBACK.

Наполняется в срезе «Фундамент платформы» до первого реального URL в краулере и
задолго до первого production-токена.
