#!/usr/bin/env bash
# Проверка расхождения контракта (v0.4 §18).
#
# Схема OpenAPI и типы TypeScript хранятся в репозитории. Если backend изменился,
# а сгенерированные файлы — нет, сборка должна падать: иначе фронтенд молча
# продолжает работать по устаревшему контракту, и расхождение всплывает уже в
# рантайме.
#
# Сравнение идёт по содержимому файлов, а не через `git diff`. Первая версия
# опиралась на git и проходила успешно даже при реальном расхождении: пока
# сгенерированные файлы не добавлены в индекс, git их не видит, и проверка
# всегда была зелёной.
set -euo pipefail

cd "$(dirname "$0")/.."

python="${PYTHON:-.venv/bin/python}"

schema="packages/schemas/openapi.json"
types="packages/schemas/src/openapi.d.ts"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

missing=0
for file in "$schema" "$types"; do
  if [[ -f "$file" ]]; then
    cp "$file" "$tmp/$(basename "$file").before"
  else
    echo "✗ Отсутствует сгенерированный файл: $file"
    missing=1
  fi
done

"$python" apps/api/scripts/export_openapi.py > /dev/null
pnpm --filter @ads-os/schemas generate > /dev/null

if [[ $missing -eq 1 ]]; then
  echo "  Файлы созданы. Закоммитьте результат."
  exit 1
fi

drift=0
for file in "$schema" "$types"; do
  if ! diff -q "$tmp/$(basename "$file").before" "$file" > /dev/null; then
    echo "✗ Расхождение в $file"
    diff --unified=2 "$tmp/$(basename "$file").before" "$file" | head -40 || true
    drift=1
  fi
done

if [[ $drift -eq 1 ]]; then
  echo
  echo "Контракт API разошёлся со сгенерированными файлами."
  echo "Файлы уже перегенерированы — проверьте изменения и закоммитьте их."
  exit 1
fi

echo "✓ Контракт API и сгенерированные типы совпадают."
