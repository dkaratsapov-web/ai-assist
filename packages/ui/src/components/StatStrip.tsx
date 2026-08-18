import type { ReactNode } from "react";
import { cn } from "../lib/cn";
import { Card } from "./Card";

export interface Stat {
  label: string;
  /** Уже отформатированное значение: «3», «1 из 2», «12 400 ₽». */
  value: string;
  /** Уточнение под числом: единица измерения, оговорка, срок. */
  note?: ReactNode;
}

export interface StatStripProps {
  items: Stat[];
  className?: string;
}

/**
 * Строка счётчиков.
 *
 * Заменяет ряд отдельных карточек под каждое число. Разница не в украшении:
 * четыре карточки на всю ширину экрана дают четыре однозначные цифры,
 * разнесённые на тысячу с лишним пикселей, — глаз проходит это расстояние
 * зря, а места они занимают как полноценный блок с содержанием.
 *
 * Здесь те же числа стоят рядом и разделены тонкой линией: они читаются одним
 * взглядом и честно занимают ровно столько, сколько весят.
 *
 * Разделители пропадают на узком экране: там колонки становятся в два ряда, и
 * вертикальная линия отделяла бы не то, что нужно.
 */
export function StatStrip({ items, className }: StatStripProps) {
  return (
    <Card className={cn("py-3", className)}>
      <div className="grid grid-cols-2 gap-x-4 gap-y-4 sm:grid-cols-4">
        {items.map((item, index) => (
          <div
            key={item.label}
            className={cn(
              "flex min-w-0 flex-col gap-0.5",
              index > 0 && "sm:border-border-subtle sm:border-l sm:pl-4",
            )}
          >
            <span className="text-caption text-text-secondary truncate">{item.label}</span>
            <span className="text-h2 text-text-primary tabular-nums">{item.value}</span>
            {item.note && <span className="text-caption text-text-secondary">{item.note}</span>}
          </div>
        ))}
      </div>
    </Card>
  );
}

export interface ProgressBarProps {
  value: number;
  total: number;
  /** Подпись для программ экранного доступа. */
  label: string;
  className?: string;
}

/**
 * Полоса выполнения.
 *
 * Нужна там, где раньше стояла надпись «2 из 10». Надпись верна, но её надо
 * прочитать и мысленно перевести в долю; полоса показывает ту же долю сразу, а
 * подпись рядом остаётся — по ней видно точное число, которого полоса не даёт.
 */
export function ProgressBar({ value, total, label, className }: ProgressBarProps) {
  const share = total > 0 ? Math.min(1, Math.max(0, value / total)) : 0;

  return (
    <div
      role="progressbar"
      aria-valuenow={value}
      aria-valuemin={0}
      aria-valuemax={total}
      aria-label={label}
      className={cn("bg-border rounded-pill h-1.5 w-full overflow-hidden", className)}
    >
      <div
        className="bg-surface-inverse rounded-pill h-full transition-[width] duration-(--duration-panel)"
        style={{ width: `${share * 100}%` }}
      />
    </div>
  );
}
