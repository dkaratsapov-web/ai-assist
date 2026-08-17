#!/usr/bin/env bash
#
# Установка самообновления. Запускается один раз.
#
# После неё сервер сам забирает изменения и пересобирается — вводить команды
# вручную больше не нужно.
#
# Расписание сделано таймером systemd, а не cron. Причина практическая: у
# таймера есть журнал. Когда обновление однажды не приедет, ответ на вопрос
# «почему» должен находиться одной командой, а не поиском по почте root.

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INTERVAL="${ADS_OS_DEPLOY_INTERVAL:-2min}"

if [ "$(id -u)" -ne 0 ]; then
    echo "Запустите от root: sudo bash infra/install-autodeploy.sh" >&2
    exit 1
fi

chmod +x "$REPO/infra/autodeploy.sh"

cat > /etc/systemd/system/ads-os-deploy.service <<EOF
[Unit]
Description=Обновление ADS OS из GitHub
# Без сети обновляться неоткуда, а попытка засорит журнал ошибкой.
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=$REPO
Environment=ADS_OS_REPO=$REPO
ExecStart=$REPO/infra/autodeploy.sh
# Сборка образов идёт минутами; жёсткий предел нужен, чтобы зависший процесс
# не занимал замок вечно и не блокировал все следующие обновления.
TimeoutStartSec=1800
EOF

cat > /etc/systemd/system/ads-os-deploy.timer <<EOF
[Unit]
Description=Проверять обновления ADS OS каждые $INTERVAL

[Timer]
OnBootSec=2min
OnUnitActiveSec=$INTERVAL
# Если сервер был выключен и пропустил срабатывание, проверить сразу после
# включения, а не ждать полного интервала.
Persistent=true

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now ads-os-deploy.timer

echo
echo "Готово. Сервер будет обновляться сам каждые $INTERVAL."
echo
echo "Посмотреть, что происходило:   journalctl -u ads-os-deploy -n 50"
echo "Обновить прямо сейчас:         systemctl start ads-os-deploy"
echo "Приостановить:                 systemctl stop ads-os-deploy.timer"
echo "Включить снова:                systemctl start ads-os-deploy.timer"
