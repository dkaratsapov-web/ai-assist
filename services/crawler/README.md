# services/crawler

Изолированный краулер. Запускается **только** в отдельном worker/service с
собственным egress policy (v0.4 §20).

Обязательно с первого дня: запрет localhost/loopback/link-local/private ranges и
metadata endpoints, DNS resolve → IP validation до запроса, повторная проверка
после каждого redirect, ограничение числа redirect, только http/https, лимиты
timeout/size/страниц, защита от decompression bombs, sandbox для headless browser.
Нет сетевого доступа к БД, Redis и внутренним админ-сервисам (v0.3 §97).
