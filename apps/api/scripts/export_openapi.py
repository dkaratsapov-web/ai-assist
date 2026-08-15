#!/usr/bin/env python
"""Выгружает схему OpenAPI в файл.

Схема — источник правды для контракта: из неё генерируются типы фронтенда,
поэтому файл лежит в репозитории и его расхождение с кодом ловится в CI
(v0.4 §18).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Экспорт схемы не должен требовать поднятой базы: он только строит приложение.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ads_os.main import create_app  # noqa: E402

DEFAULT_OUTPUT = Path(__file__).resolve().parents[3] / "packages" / "schemas" / "openapi.json"


def main() -> int:
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUTPUT
    output.parent.mkdir(parents=True, exist_ok=True)

    schema = create_app().openapi()
    # Ключи сортируются, отступ фиксирован: иначе каждая выгрузка давала бы
    # шум в diff и проверка расхождения теряла бы смысл.
    output.write_text(
        json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"OpenAPI выгружен: {output} ({len(schema['paths'])} путей)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
