"use client";

import type { ReactNode } from "react";
import { cn } from "../lib/cn";

export interface FilterOption {
  value: string;
  label: string;
  /** Количество элементов в группе. Показывается рядом с подписью. */
  count?: number;
}

export interface FilterBarProps {
  options: FilterOption[];
  value: string;
  onChange: (value: string) => void;
  /** Подпись группы для скринридера, например «Фильтр проектов». */
  label: string;
  /** Дополнительные контролы справа: поиск, период, кнопка. */
  actions?: ReactNode;
  className?: string;
}

/**
 * Панель фильтров.
 *
 * Активный фильтр выделяется мягким тёмным фоном, а не ярким цветом —
 * акцентные цвета зарезервированы за смысловыми состояниями (v0.3 §119).
 */
export function FilterBar({ options, value, onChange, label, actions, className }: FilterBarProps) {
  return (
    <div className={cn("flex flex-wrap items-center justify-between gap-4", className)}>
      <div role="group" aria-label={label} className="flex flex-wrap items-center gap-1.5">
        {options.map((option) => {
          const active = option.value === value;
          return (
            <button
              key={option.value}
              type="button"
              aria-pressed={active}
              onClick={() => onChange(option.value)}
              className={cn(
                "rounded-pill text-caption inline-flex items-center gap-1.5 px-3 py-1.5 font-medium",
                "focus-visible:outline-focus focus-visible:outline-2 focus-visible:outline-offset-2",
                "transition-colors duration-(--duration-fast) ease-out max-sm:min-h-11",
                active
                  ? "bg-cta text-cta-text"
                  : "bg-bg-secondary text-text-secondary hover:bg-surface-active",
              )}
            >
              {option.label}
              {option.count !== undefined && (
                <span className={cn("text-micro", active ? "opacity-70" : "text-text-secondary")}>
                  {option.count}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}
