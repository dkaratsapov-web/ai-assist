"use client";

import type { ReactNode } from "react";
import { cn } from "../lib/cn";
import { EmptyState } from "./EmptyState";
import { ErrorState } from "./ErrorState";
import { Skeleton } from "./Skeleton";

export interface DataTableColumn<Row> {
  key: string;
  header: ReactNode;
  render: (row: Row) => ReactNode;
  align?: "left" | "right";
  /** Ширина колонки, например «12rem». По умолчанию — по содержимому. */
  width?: string;
  /** Числовая колонка: моноширинные цифры и выравнивание вправо. */
  numeric?: boolean;
}

export interface DataTableProps<Row> {
  columns: DataTableColumn<Row>[];
  rows: Row[];
  rowKey: (row: Row) => string;
  onRowClick?: (row: Row) => void;
  loading?: boolean;
  error?: { title: string; requestId?: string; onRetry?: () => void };
  empty?: { title: string; description?: string };
  /** Подпись таблицы для скринридера. */
  caption: string;
  className?: string;
}

/**
 * Таблица.
 *
 * Горизонтальный скролл здесь предусмотрен намеренно и ограничен контейнером —
 * страница целиком по горизонтали не едет (v0.3 §150). Заголовок липкий, чтобы
 * при длинных списках было понятно, что за колонка перед глазами.
 *
 * Состояния loading / empty / error встроены: таблица без них считается
 * недоделанной.
 */
export function DataTable<Row>({
  columns,
  rows,
  rowKey,
  onRowClick,
  loading = false,
  error,
  empty,
  caption,
  className,
}: DataTableProps<Row>) {
  if (error) {
    return <ErrorState title={error.title} requestId={error.requestId} onRetry={error.onRetry} />;
  }

  if (!loading && rows.length === 0) {
    return (
      <EmptyState title={empty?.title ?? "Пока нет данных"} description={empty?.description} />
    );
  }

  return (
    <div className={cn("border-border rounded-small-card overflow-x-auto border", className)}>
      <table className="w-full border-collapse text-left">
        <caption className="sr-only">{caption}</caption>

        <thead className="bg-bg-secondary sticky top-0 z-10">
          <tr>
            {columns.map((column) => (
              <th
                key={column.key}
                scope="col"
                style={column.width ? { width: column.width } : undefined}
                className={cn(
                  "text-micro text-text-secondary border-border border-b px-3 py-2.5 font-medium whitespace-nowrap",
                  (column.align ?? (column.numeric ? "right" : "left")) === "right" && "text-right",
                )}
              >
                {column.header}
              </th>
            ))}
          </tr>
        </thead>

        <tbody>
          {loading
            ? Array.from({ length: 5 }, (_, i) => (
                <tr key={`skeleton-${i}`} className="border-border-subtle border-b last:border-b-0">
                  {columns.map((column) => (
                    <td key={column.key} className="px-3 py-3">
                      <Skeleton className="h-3.5 w-full max-w-28" />
                    </td>
                  ))}
                </tr>
              ))
            : rows.map((row) => (
                <tr
                  key={rowKey(row)}
                  onClick={onRowClick ? () => onRowClick(row) : undefined}
                  className={cn(
                    "border-border-subtle border-b last:border-b-0",
                    onRowClick && "hover:bg-surface-hover cursor-pointer",
                    "transition-colors duration-(--duration-fast) ease-out",
                  )}
                >
                  {columns.map((column) => (
                    <td
                      key={column.key}
                      className={cn(
                        "text-body-sm text-text-primary px-3 py-3",
                        (column.align ?? (column.numeric ? "right" : "left")) === "right" &&
                          "text-right",
                        column.numeric && "tabular-nums",
                      )}
                    >
                      {column.render(row)}
                    </td>
                  ))}
                </tr>
              ))}
        </tbody>
      </table>
    </div>
  );
}
