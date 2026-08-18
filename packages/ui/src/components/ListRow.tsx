import type { ReactNode } from "react";
import { cn } from "../lib/cn";

export interface ListRowProps {
  /** Главное: фраза, адрес, имя. */
  title: ReactNode;
  /** Вторая строка: откуда взялось, почему так решено. */
  meta?: ReactNode;
  /** Числа справа: частотность, балл, количество. */
  value?: ReactNode;
  /** Действия и метки справа от значения. */
  action?: ReactNode;
  /** Клик по всей строке. Включает подсветку при наведении. */
  onClick?: () => void;
  className?: string;
}

/**
 * Строка списка.
 *
 * В продукте полтора десятка списков — фразы, конкуренты, проверки, участники,
 * группы, — и каждый был свёрстан заново. Отличались отступы, толщина
 * разделителя, положение чисел: одинаковые по смыслу списки выглядели разными,
 * а разница ничего не значила.
 *
 * Что здесь решено раз и навсегда:
 *
 * **Разделитель, а не рамка.** Полоса между строками тоньше и светлее границы
 * карточки — иначе список читается как таблица из клеток. У последней строки
 * разделителя нет: он рисовал бы вторую границу поверх края карточки.
 *
 * **Числа справа и моноширинно.** Цифры разной ширины ломают колонку, и
 * сравнить «5400» с «900» становится нельзя, хотя ради сравнения список и
 * существует.
 *
 * **Подсветка только у кликабельных.** Строка, которая подсвечивается, но
 * никуда не ведёт, — обещание, которого интерфейс не выполняет.
 */
export function ListRow({ title, meta, value, action, onClick, className }: ListRowProps) {
  const content = (
    <>
      <div className="flex min-w-0 flex-col gap-0.5">
        <span className="text-body-sm text-text-primary">{title}</span>
        {meta && <span className="text-caption text-text-secondary">{meta}</span>}
      </div>
      {(value || action) && (
        <div className="flex shrink-0 items-center gap-3">
          {value && <span className="text-caption text-text-secondary tabular-nums">{value}</span>}
          {action}
        </div>
      )}
    </>
  );

  const shared = cn(
    "border-border-subtle flex flex-wrap items-center justify-between gap-x-4 gap-y-1",
    "border-b py-2.5 last:border-b-0",
    className,
  );

  if (!onClick) {
    return <div className={shared}>{content}</div>;
  }

  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        shared,
        "-mx-2 w-[calc(100%+1rem)] px-2 text-left",
        "rounded-control hover:bg-surface-hover transition-colors duration-(--duration-fast)",
        "focus-visible:outline-focus focus-visible:outline-2 focus-visible:outline-offset-2",
      )}
    >
      {content}
    </button>
  );
}
