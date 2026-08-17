#!/usr/bin/env bash
#
# Проверка готовности стенда к работе (v0.3 §114).
#
#     bash infra/preflight.sh
#
# Проверяет то, что нельзя проверить глазами и о чём вспоминают после аварии:
# не смотрят ли база и очередь в интернет, есть ли у краулера путь к базе, не
# попали ли секреты в git, отдаётся ли сайт по HTTPS, делаются ли резервные
# копии.
#
# Пока проверки не пройдены, боевой доступ к Директу включать нельзя. Это не
# формальность: до тех пор система работает с чужими рекламными бюджетами
# только понарошку, и цена ошибки равна нулю. После — не равна.
#
# Код возврата: 0 — всё сошлось, 1 — есть хотя бы одно нарушение.

set -uo pipefail

RED=$'\033[31m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; BOLD=$'\033[1m'; OFF=$'\033[0m'

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$REPO_ROOT/infra/.env"

FAILED=0
WARNED=0

pass() { printf '  %s✓%s %s\n' "$GREEN" "$OFF" "$1"; }
fail() { printf '  %s✗%s %s\n' "$RED" "$OFF" "$1"; FAILED=$((FAILED + 1)); }
warn() { printf '  %s!%s %s\n' "$YELLOW" "$OFF" "$1"; WARNED=$((WARNED + 1)); }
head2() { printf '\n%s%s%s\n' "$BOLD" "$1" "$OFF"; }

env_value() {
  [ -f "$ENV_FILE" ] || return 1
  grep -E "^$1=" "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '"'"'"' \r'
}

printf '\n%sПроверка готовности ADS OS%s\n' "$BOLD" "$OFF"

# ─── Секреты ──────────────────────────────────────────────────────────────────

head2 "Секреты"

if [ -f "$ENV_FILE" ]; then
  pass "infra/.env на месте"

  PERMS="$(stat -c '%a' "$ENV_FILE" 2>/dev/null || echo '?')"
  if [ "$PERMS" = "600" ]; then
    pass "права на infra/.env — только владелец"
  else
    warn "права на infra/.env = $PERMS, стоит поставить 600: chmod 600 infra/.env"
  fi
else
  fail "нет infra/.env — скопируйте .env.example и заполните"
fi

if git -C "$REPO_ROOT" ls-files --error-unmatch infra/.env >/dev/null 2>&1; then
  fail "infra/.env отслеживается git — секреты попадут в репозиторий"
else
  pass "infra/.env вне git"
fi

# Ключи в собранном фронтенде. Проверка дешёвая, а ошибка дорогая: секрет,
# попавший в бандл, виден любому посетителю через исходники страницы.
if [ -d "$REPO_ROOT/apps/web/.next" ]; then
  LEAKED=$(grep -rlE 'YANDEX_DIRECT_TOKEN|YANDEX_OAUTH_CLIENT_SECRET|OPENAI_API_KEY' \
    "$REPO_ROOT/apps/web/.next" 2>/dev/null | head -3)
  if [ -n "$LEAKED" ]; then
    fail "имена секретов найдены в сборке фронтенда — проверьте: $LEAKED"
  else
    pass "секретов в сборке фронтенда нет"
  fi
fi

for VAR in POSTGRES_PASSWORD YANDEX_OAUTH_CLIENT_ID YANDEX_OAUTH_CLIENT_SECRET BOOTSTRAP_OWNER_EMAIL; do
  VALUE="$(env_value "$VAR" || true)"
  if [ -n "$VALUE" ]; then
    pass "$VAR заполнен"
  else
    fail "$VAR пустой"
  fi
done

# ─── Сеть ─────────────────────────────────────────────────────────────────────

head2 "Сеть"

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  cd "$REPO_ROOT/infra" || exit 1

  RUNNING_LIST=$(docker compose ps --status running --format '{{.Service}}' 2>/dev/null)
  RUNNING=$(printf '%s' "$RUNNING_LIST" | grep -c . || true)

  # Опубликованный порт базы — самая частая и самая дорогая ошибка: PostgreSQL
  # с паролем в интернете подбирают за часы.
  #
  # Пустой ответ на остановленном стенде — не то же самое, что «портов нет».
  # Молчаливая галочка здесь опаснее отсутствия проверки: на неё сошлются.
  if [ "$RUNNING" -eq 0 ]; then
    warn "стенд не запущен — публикацию портов проверить не удалось"
  else
    PUBLISHED=$(docker compose ps --format '{{.Service}} {{.Publishers}}' 2>/dev/null \
      | grep -E 'postgres|redis' | grep -E '0\.0\.0\.0|:::' || true)
    if [ -n "$PUBLISHED" ]; then
      fail "база или очередь опубликованы наружу: $PUBLISHED"
    else
      pass "база и очередь портов наружу не публикуют"
    fi
  fi

  # Краулер ходит по чужим сайтам. Путь от него к базе означает, что ловушка на
  # чужой странице может добраться до данных всех клиентов.
  CRAWLER_NETS=$(docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}' \
    "$(docker compose ps -q crawler-worker 2>/dev/null)" 2>/dev/null || true)
  PG_NETS=$(docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}' \
    "$(docker compose ps -q postgres 2>/dev/null)" 2>/dev/null || true)

  if [ -n "$CRAWLER_NETS" ] && [ -n "$PG_NETS" ]; then
    SHARED=""
    for NET in $CRAWLER_NETS; do
      case " $PG_NETS " in *" $NET "*) SHARED="$NET";; esac
    done
    if [ -n "$SHARED" ]; then
      fail "краулер и база в одной сети ($SHARED) — изоляция не работает"
    else
      pass "у краулера нет пути к базе"
    fi
  else
    warn "контейнеры не запущены — изоляцию краулера проверить не удалось"
  fi

  if [ "$RUNNING" -ge 6 ]; then
    pass "служб запущено: $RUNNING"
  else
    warn "запущено всего $RUNNING служб — проверьте docker compose ps"
  fi
else
  warn "Docker недоступен — проверки сети пропущены"
fi

# ─── Домен и сертификат ───────────────────────────────────────────────────────

head2 "Домен"

DOMAIN="$(env_value DOMAIN || true)"

if [ -z "$DOMAIN" ]; then
  fail "DOMAIN не задан в infra/.env"
else
  pass "домен: $DOMAIN"

  if curl -fsS --max-time 10 "https://$DOMAIN/api/v1/health" >/dev/null 2>&1; then
    pass "HTTPS работает, сертификат принят"
  else
    warn "https://$DOMAIN пока не отвечает — проверьте A-запись и подождите выпуска сертификата"
  fi

  # HTTP обязан уводить на HTTPS, а не отдавать содержимое.
  CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "http://$DOMAIN" 2>/dev/null || echo 000)
  case "$CODE" in
    301|302|308) pass "HTTP перенаправляет на HTTPS" ;;
    000) warn "HTTP не отвечает — возможно, домен ещё не указывает сюда" ;;
    *) fail "HTTP отвечает кодом $CODE вместо перенаправления" ;;
  esac
fi

# ─── Резервные копии ──────────────────────────────────────────────────────────

head2 "Резервные копии"

BACKUP_DIR="$REPO_ROOT/infra/backups"
if [ -d "$BACKUP_DIR" ]; then
  COUNT=$(find "$BACKUP_DIR" -name '*.sql.gz' 2>/dev/null | wc -l)
  LATEST=$(find "$BACKUP_DIR" -name '*.sql.gz' -mtime -1 2>/dev/null | head -1)

  if [ "$COUNT" -eq 0 ]; then
    fail "резервных копий нет — служба backup не отработала ни разу"
  elif [ -z "$LATEST" ]; then
    fail "копий $COUNT, но свежее суток нет — потеря данных превысит норматив (v0.4 §14)"
  else
    pass "копий: $COUNT, свежая есть"
  fi
else
  warn "папки infra/backups нет — служба backup ещё не запускалась"
fi

# ─── Рекламный кабинет ────────────────────────────────────────────────────────

head2 "Рекламный кабинет"

ADAPTER="$(env_value AD_PLATFORM_ADAPTER || echo mock)"
APPROVED="$(env_value AD_PLATFORM_LIVE_APPROVED || echo false)"
SANDBOX="$(env_value YANDEX_DIRECT_SANDBOX || echo true)"

if [ "$ADAPTER" = "mock" ]; then
  pass "работает заглушка — чужие бюджеты недосягаемы"
else
  if [ "$APPROVED" != "true" ]; then
    pass "предохранитель на месте: адаптер боевой, но доступ не разрешён"
  elif [ "$FAILED" -gt 0 ]; then
    fail "боевой доступ разрешён, но проверки выше не пройдены — выключите AD_PLATFORM_LIVE_APPROVED"
  elif [ "$SANDBOX" = "true" ]; then
    pass "боевой адаптер в песочнице — настоящие деньги не затронуты"
  else
    warn "БОЕВОЙ РЕЖИМ: действия касаются настоящих рекламных бюджетов"
  fi
fi

# ─── Итог ─────────────────────────────────────────────────────────────────────

printf '\n%s' "$BOLD"
if [ "$FAILED" -eq 0 ] && [ "$WARNED" -eq 0 ]; then
  printf 'Всё сошлось. Стенд готов.%s\n\n' "$OFF"
  exit 0
elif [ "$FAILED" -eq 0 ]; then
  printf 'Нарушений нет, замечаний: %d.%s\n' "$WARNED" "$OFF"
  printf 'Замечания не блокируют работу, но боевой доступ к Директу лучше включать без них.\n\n'
  exit 0
else
  printf 'Нарушений: %d, замечаний: %d.%s\n' "$FAILED" "$WARNED" "$OFF"
  printf 'Боевой доступ к Директу включать нельзя, пока нарушения не устранены.\n\n'
  exit 1
fi
