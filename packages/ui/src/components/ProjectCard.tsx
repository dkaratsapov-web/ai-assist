import type { ProjectStatusKey } from "@ads-os/tokens";
import { cn } from "../lib/cn";
import { Card } from "./Card";
import { ProjectStatusBadge } from "./StatusBadge";
import { Sparkline } from "./Sparkline";
import { formatCurrency, formatNumber } from "../lib/format";

export interface ProjectCardProps {
  name: string;
  status: ProjectStatusKey;
  spend: number;
  leads: number;
  cpl: number;
  trend?: number[];
  onClick?: () => void;
  className?: string;
}

/**
 * Карточка проекта в списке.
 *
 * Показывает минимально достаточный набор: основной KPI виден без перехода
 * внутрь проекта (v0.3 §129).
 */
export function ProjectCard({
  name,
  status,
  spend,
  leads,
  cpl,
  trend,
  onClick,
  className,
}: ProjectCardProps) {
  return (
    <Card
      padding="md"
      interactive={Boolean(onClick)}
      className={cn(
        onClick &&
          "focus-within:outline-focus relative cursor-pointer focus-within:outline-2 focus-within:outline-offset-2",
        className,
      )}
    >
      <div className="mb-3 flex items-start justify-between gap-4">
        <div className="min-w-0">
          {onClick ? (
            <button
              type="button"
              onClick={onClick}
              className="text-h3 text-text-primary block max-w-full truncate text-left outline-none"
            >
              {/* Растянутая область клика: вся карточка кликабельна, но в дереве
                  доступности остаётся одна кнопка с понятным именем. */}
              <span className="absolute inset-0" aria-hidden="true" />
              {name}
            </button>
          ) : (
            <h3 className="text-h3 text-text-primary truncate">{name}</h3>
          )}
        </div>
        <ProjectStatusBadge status={status} dot />
      </div>

      <div className="flex items-end justify-between gap-4">
        <dl className="flex min-w-0 flex-wrap gap-4">
          <Metric label="Расходы" value={formatCurrency(spend)} />
          <Metric label="Лиды" value={formatNumber(leads)} />
          <Metric label="CPL" value={formatCurrency(cpl)} />
        </dl>
        {trend && trend.length > 1 && (
          <Sparkline values={trend} width={80} height={32} className="shrink-0" />
        )}
      </div>
    </Card>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-micro text-text-secondary">{label}</dt>
      <dd className="text-body-sm text-text-primary font-medium tabular-nums">{value}</dd>
    </div>
  );
}
