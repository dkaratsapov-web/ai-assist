import type { MetricAvailabilityKey } from "@ads-os/tokens";
import { cn } from "../lib/cn";
import { Card } from "./Card";
import { MetricTrend, type MetricPolarity } from "./MetricTrend";
import { Sparkline } from "./Sparkline";
import { Skeleton } from "./Skeleton";
import { StatusBadge } from "./StatusBadge";
import { IconLock } from "../icons";

export interface KpiCardProps {
  label: string;
  /** Уже отформатированное значение: «142 750 ₽», «535 ₽», «267». */
  value: string;
  delta?: number;
  polarity?: MetricPolarity;
  period?: string;
  trend?: number[];
  /** Цвет серии. Одна метрика — один цвет во всём продукте (v0.4 §19). */
  seriesColor?: string;
  /**
   * Достоверность метрики.
   *
   * `proxy` — считается по временному заменителю: экономика не заполнена
   * (Limited Economics Mode, v0.4 §5) либо продажи ещё не подключены
   * (Limited Attribution Mode, решение B в v0.4-decisions).
   * `unavailable` — источник не подключён, число показывать нельзя.
   */
  availability?: MetricAvailabilityKey;
  /** Что сделать, чтобы метрика стала достоверной. */
  availabilityHint?: string;
  loading?: boolean;
  className?: string;
}

/**
 * Карточка KPI.
 *
 * Ключевое отличие от обычного счётчика: карточка честно показывает, что метрика
 * является оценкой или недоступна, вместо того чтобы рисовать правдоподобное
 * число. Источники подключаются постепенно (Метрика — на одном этапе, CRM — на
 * другом), и до подключения CRM выручка и CAC достоверными не являются.
 */
export function KpiCard({
  label,
  value,
  delta,
  polarity = "neutral",
  period,
  trend,
  seriesColor = "var(--color-chart-1)",
  availability = "available",
  availabilityHint,
  loading = false,
  className,
}: KpiCardProps) {
  if (loading) {
    return (
      <Card className={cn("flex flex-col gap-3", className)}>
        <Skeleton className="h-3.5 w-20" />
        <Skeleton className="h-7 w-28" />
        <Skeleton className="h-3 w-24" />
      </Card>
    );
  }

  const isUnavailable = availability === "unavailable";

  return (
    <Card className={cn("flex flex-col justify-between gap-3", className)}>
      <div className="flex items-start justify-between gap-2">
        <span className="text-caption text-text-secondary">{label}</span>
        {availability === "proxy" && (
          <StatusBadge
            tone="warning"
            title={availabilityHint}
            aria-label={availabilityHint ? `Оценка. ${availabilityHint}` : undefined}
          >
            Оценка
          </StatusBadge>
        )}
      </div>

      {isUnavailable ? (
        <div className="flex flex-col gap-1.5">
          <span className="text-h3 text-text-disabled flex items-center gap-1.5">
            <IconLock size={16} aria-hidden="true" />
            Нет данных
          </span>
          {availabilityHint && (
            <span className="text-micro text-text-secondary">{availabilityHint}</span>
          )}
        </div>
      ) : (
        <div className="flex items-end justify-between gap-4">
          <div className="flex min-w-0 flex-col gap-1.5">
            <span className="text-metric text-text-primary whitespace-nowrap tabular-nums">
              {value}
            </span>
            {delta !== undefined && (
              <MetricTrend delta={delta} polarity={polarity} period={period} />
            )}
          </div>
          {/* Мини-график уступает место значению: число обязано помещаться в
              одну строку, график — вспомогательный. */}
          {trend && trend.length > 1 && (
            <Sparkline values={trend} color={seriesColor} width={72} className="min-w-0 shrink" />
          )}
        </div>
      )}
    </Card>
  );
}
