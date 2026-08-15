# services/analytics

Аналитический слой. Изолирован как отдельный repository, чтобы при росте нагрузки
его можно было вынести из PostgreSQL без переписывания вызывающего кода (v0.4 §12).

Требования к схеме: статистические и search-query таблицы partition-ready с первой
миграции, партиционирование по дате, индексы под `project_id + date + campaign_id`,
raw events и агрегаты разделены.

Все аналитические ответы несут `as_of` и `source` — этого требует Data Freshness
Matrix (v0.4 §9) и Source-of-Truth Matrix (v0.4 §8).
