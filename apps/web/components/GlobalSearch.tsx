"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import type { SearchResult } from "@ads-os/schemas";
import { SearchInput, StatusBadge } from "@ads-os/ui";
import { createApiClient } from "@/lib/api";

/** Задержка перед запросом. Без неё на каждую букву уходит отдельный запрос. */
const DEBOUNCE_MS = 250;

/** Короче двух букв искать бессмысленно: находится всё. */
const MIN_QUERY = 2;

/**
 * Поиск по проектам и фразам.
 *
 * Поле в шапке было всегда, но ничего не делало — ровно та же болезнь, что
 * была у колокольчика. Элемент, который выглядит рабочим и не отвечает, хуже
 * его отсутствия: человек решает, что сломан сервис, а не что функции нет.
 */
export function GlobalSearch() {
  const api = useMemo(() => createApiClient(), []);
  const router = useRouter();

  const [query, setQuery] = useState("");
  const [result, setResult] = useState<SearchResult | null>(null);
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const needle = query.trim();
    if (needle.length < MIN_QUERY) return;

    let ignore = false;
    const timer = setTimeout(() => {
      void (async () => {
        try {
          const found = await api.search(needle);
          if (!ignore) {
            setResult(found);
            setOpen(true);
          }
        } catch {
          // Не вошёл или сервис недоступен. Показывать экран ошибки поверх
          // работающей страницы из-за поиска незачем.
          if (!ignore) setResult(null);
        }
      })();
    }, DEBOUNCE_MS);

    return () => {
      ignore = true;
      clearTimeout(timer);
    };
  }, [api, query]);

  // Клик мимо закрывает подсказку: она перекрывает содержимое страницы.
  useEffect(() => {
    const onClick = (event: MouseEvent) => {
      if (box.current && !box.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  const go = (href: string) => {
    setOpen(false);
    setQuery("");
    router.push(href);
  };

  // Подсказка выводится из запроса, а не гасится отдельным состоянием: иначе
  // при стирании строки на мгновение виден прошлый результат.
  const shown = query.trim().length >= MIN_QUERY ? result : null;
  const nothing = shown !== null && shown.projects.length === 0 && shown.keywords.length === 0;

  return (
    <div ref={box} className="relative">
      <SearchInput
        placeholder="Поиск по проектам и фразам…"
        shortcut="⌘K"
        aria-label="Поиск по проектам и ключевым фразам"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onFocus={() => result && setOpen(true)}
      />

      {open && shown && (
        <div className="border-border bg-bg rounded-control absolute top-full right-0 left-0 z-20 mt-1 max-h-96 overflow-y-auto border p-2 shadow-lg">
          {nothing && (
            <p className="text-body-sm text-text-secondary p-2">
              Ничего не нашлось. Поиск ищет по названиям проектов и по загруженным фразам.
            </p>
          )}

          {shown.projects.length > 0 && (
            <>
              <p className="text-micro text-text-secondary px-2 py-1 tracking-wide uppercase">
                Проекты
              </p>
              {shown.projects.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => go(`/projects/${item.id}`)}
                  className="hover:bg-surface-hover rounded-control text-body-sm text-text-primary block w-full px-2 py-1.5 text-left"
                >
                  {item.name}
                </button>
              ))}
            </>
          )}

          {shown.keywords.length > 0 && (
            <>
              <p className="text-micro text-text-secondary px-2 py-1 tracking-wide uppercase">
                Фразы
              </p>
              {shown.keywords.map((item) => (
                <button
                  key={`${item.project_id}-${item.phrase}`}
                  type="button"
                  onClick={() => go(`/semantics?project=${item.project_id}`)}
                  className="hover:bg-surface-hover rounded-control flex w-full items-center justify-between gap-2 px-2 py-1.5 text-left"
                >
                  <span className="flex min-w-0 flex-col">
                    <span className="text-body-sm text-text-primary truncate">{item.phrase}</span>
                    {/* Проект обязателен: «остекление балконов» есть у половины
                        клиентов, и без проекта строка ни о чём не говорит. */}
                    <span className="text-caption text-text-secondary truncate">
                      {item.project_name}
                    </span>
                  </span>
                  {item.intent === "irrelevant" && (
                    <StatusBadge tone="critical">нецелевой</StatusBadge>
                  )}
                </button>
              ))}
            </>
          )}
        </div>
      )}
    </div>
  );
}
