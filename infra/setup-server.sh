#!/usr/bin/env bash
#
# Первичная настройка чистого сервера под ADS OS.
#
# Рассчитан на Ubuntu 22.04 или 24.04 у Timeweb, Beget или любого другого
# хостинга: ничего специфичного для конкретного провайдера здесь нет.
#
# Запускается один раз, от root:
#
#     bash infra/setup-server.sh
#
# Повторный запуск безопасен: всё, что уже сделано, пропускается. Это не
# вежливость, а необходимость — установка на медленной машине занимает минуты
# и вполне может оборваться на середине.
#
# Что делает: ставит Docker, создаёт файл подкачки, закрывает firewall, готовит
# infra/.env и поднимает стенд. Чего не делает: не трогает DNS и не выпускает
# сертификат — этим занимается Caddy сам, когда домен начнёт указывать сюда.

set -euo pipefail

RED=$'\033[31m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; BOLD=$'\033[1m'; OFF=$'\033[0m'

step() { printf '\n%s==> %s%s\n' "$BOLD" "$1" "$OFF"; }
ok()   { printf '  %s✓%s %s\n' "$GREEN" "$OFF" "$1"; }
warn() { printf '  %s!%s %s\n' "$YELLOW" "$OFF" "$1"; }
die()  { printf '\n%sОстановка:%s %s\n\n' "$RED" "$OFF" "$1" >&2; exit 1; }

[ "$(id -u)" = "0" ] || die "Запускать нужно от root: sudo bash infra/setup-server.sh"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$REPO_ROOT/infra/.env"

# ─── 1. Память ────────────────────────────────────────────────────────────────
#
# Сборка фронтенда — самый прожорливый шаг всей установки: на замерах пик
# доходил до 2 ГБ. Запущенный сервис в те же 2 ГБ помещается свободно, а вот
# собрать себя на такой машине без подкачки не может: Docker убивает сборку по
# нехватке памяти, и выглядит это как непонятная ошибка на середине.

step "Память"

TOTAL_MB=$(free -m | awk '/^Mem:/ {print $2}')
SWAP_MB=$(free -m | awk '/^Swap:/ {print $2}')
ok "оперативной памяти: ${TOTAL_MB} МБ, подкачки: ${SWAP_MB} МБ"

if [ "$SWAP_MB" -lt 2048 ] && [ "$TOTAL_MB" -lt 4096 ]; then
  if [ -f /swapfile ]; then
    warn "/swapfile уже есть, но не подключён — подключаю"
  else
    step "Создаю файл подкачки на 2 ГБ"
    fallocate -l 2G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=2048
    chmod 600 /swapfile
    mkswap /swapfile >/dev/null
  fi
  swapon /swapfile 2>/dev/null || true
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
  ok "подкачка подключена и переживёт перезагрузку"
elif [ "$TOTAL_MB" -ge 4096 ]; then
  ok "памяти достаточно, подкачка не нужна"
else
  ok "подкачка уже настроена"
fi

# ─── 2. Docker ────────────────────────────────────────────────────────────────

step "Docker"

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  ok "уже установлен: $(docker --version)"
else
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq ca-certificates curl gnupg git ufw >/dev/null

  install -m 0755 -d /etc/apt/keyrings
  if [ ! -f /etc/apt/keyrings/docker.asc ]; then
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
  fi

  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    > /etc/apt/sources.list.d/docker.list

  apt-get update -qq
  apt-get install -y -qq docker-ce docker-ce-cli containerd.io \
    docker-buildx-plugin docker-compose-plugin >/dev/null

  systemctl enable --now docker >/dev/null 2>&1 || true
  ok "установлен: $(docker --version)"
fi

# ─── 3. Firewall ──────────────────────────────────────────────────────────────
#
# Наружу открыты только веб и SSH. База и очередь в docker-compose и так не
# публикуют портов, но firewall — вторая линия: одна опечатка в compose не
# должна выставлять PostgreSQL в интернет (v0.3 §102).

step "Firewall"

if command -v ufw >/dev/null 2>&1; then
  ufw allow 22/tcp  >/dev/null 2>&1 || true
  ufw allow 80/tcp  >/dev/null 2>&1 || true
  ufw allow 443/tcp >/dev/null 2>&1 || true
  ufw --force enable >/dev/null 2>&1 || true
  ok "открыты только 22, 80 и 443"
else
  warn "ufw не установлен — проверьте firewall провайдера вручную"
fi

# ─── 4. Настройки ─────────────────────────────────────────────────────────────

step "Файл настроек"

if [ -f "$ENV_FILE" ]; then
  ok "infra/.env уже есть — не трогаю"
else
  cp "$REPO_ROOT/infra/.env.example" "$ENV_FILE"
  chmod 600 "$ENV_FILE"

  # Пароль базы генерируется здесь и никуда не передаётся. Заводить его руками
  # значит однажды поставить одинаковый на двух стендах.
  PASSWORD="$(head -c 32 /dev/urandom | base64 | tr -d '/+=' | head -c 32)"
  sed -i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=${PASSWORD}|" "$ENV_FILE"

  ok "создан infra/.env, пароль базы сгенерирован"
  warn "остальное заполните сами: домен, ключи Яндекс ID, почта владельца"
fi

# ─── 5. Запуск ────────────────────────────────────────────────────────────────

step "Сборка и запуск"

warn "первая сборка занимает 5–15 минут — это нормально"
cd "$REPO_ROOT/infra"
docker compose --env-file .env up -d --build

# ─── Итог ─────────────────────────────────────────────────────────────────────

DOMAIN_VALUE="$(grep -E '^DOMAIN=' "$ENV_FILE" | cut -d= -f2- || true)"
IP="$(curl -fsS --max-time 5 https://api.ipify.org 2>/dev/null || echo 'адрес не определился')"

cat <<INFO

${BOLD}Готово.${OFF}

  Адрес сервера: ${BOLD}${IP}${OFF}
  Домен:         ${DOMAIN_VALUE:-не задан}

${BOLD}Что осталось:${OFF}

  1. В панели управления доменом поставьте A-запись:
       ${DOMAIN_VALUE:-ai-helper.pro}  →  ${IP}
     Сертификат Caddy выпустит сам, как только домен начнёт указывать сюда.
     Обычно это занимает от нескольких минут до часа.

  2. Заполните infra/.env: ключи Яндекс ID и BOOTSTRAP_OWNER_EMAIL —
     без них войти будет нельзя. После правки:
       cd ${REPO_ROOT}/infra && docker compose --env-file .env up -d

  3. Проверьте готовность:
       bash ${REPO_ROOT}/infra/preflight.sh

${BOLD}Полезное:${OFF}

  Состояние:  cd ${REPO_ROOT}/infra && docker compose ps
  Журналы:    cd ${REPO_ROOT}/infra && docker compose logs -f api
  Обновление: cd ${REPO_ROOT} && git pull && cd infra && docker compose --env-file .env up -d --build

INFO
