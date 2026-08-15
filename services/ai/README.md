# services/ai

AI-слой: абстракция провайдера, structured output, валидация, confidence.

Обязательная цепочка (v0.3 §8): LLM → Structured Output → Validation →
Business Rules → Policy Engine → Action. Прямой путь LLM → Direct API запрещён.

Режимы данных (v0.4 §2.3): `SAFE_PUBLIC` — сайт, конкуренты, семантика,
обезличенная аналитика. `SENSITIVE` — PII и CRM, по умолчанию внешнему провайдеру
не отправляются.
