#!/bin/sh
# Резервная копия базы (v0.4 §14: потеря не больше суток, восстановление не
# дольше четырёх часов).
#
# Копия делается в сжатом виде и складывается рядом с датой в имени. Старые
# удаляются по числу файлов, а не по возрасту: диск на небольшой машине кончится
# раньше, чем накопится месяц, и «удалять старше 30 дней» ничего не спасёт.
set -eu

KEEP=${BACKUP_KEEP:-14}
DIR=/backups
STAMP=$(date -u +%Y-%m-%d_%H-%M)
FILE="$DIR/ads_os_$STAMP.sql.gz"

mkdir -p "$DIR"

# Пишем во временный файл и переименовываем в конце. Прерванный дамп иначе
# остаётся лежать как обычная копия, и обнаруживается это при восстановлении —
# то есть в худший возможный момент.
TMP="$FILE.part"

echo "снимаю копию: $FILE"
pg_dump --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --host postgres --no-owner \
  | gzip -9 > "$TMP"

mv "$TMP" "$FILE"

SIZE=$(wc -c < "$FILE")
if [ "$SIZE" -lt 1024 ]; then
  echo "копия подозрительно мала ($SIZE байт) — оставляю, но это повод проверить" >&2
fi

# Ротация: оставляем KEEP самых свежих.
COUNT=$(ls -1 "$DIR"/ads_os_*.sql.gz 2>/dev/null | wc -l)
if [ "$COUNT" -gt "$KEEP" ]; then
  ls -1t "$DIR"/ads_os_*.sql.gz | tail -n +$((KEEP + 1)) | while read -r old; do
    echo "удаляю старую копию: $old"
    rm -f "$old"
  done
fi

echo "готово, копий на диске: $(ls -1 "$DIR"/ads_os_*.sql.gz | wc -l)"
