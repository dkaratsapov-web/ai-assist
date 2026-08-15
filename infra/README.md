# infra

Окружения, деплой, CI/CD.

Целевой хостинг ещё не выбран — это открытое решение из v0.4 §25
(`hosting region / provider`). До его принятия локальная разработка ведётся через
docker-compose, а инфраструктурные манифесты не фиксируются.

Требования к SDLC зафиксированы в v0.3 §108: раздельные dev/staging/prod,
protected branches, SAST + dependency scan + secret scan, lockfiles, минимальные
базовые образы, контейнеры не под root, отсутствие debug-endpoint в production.
