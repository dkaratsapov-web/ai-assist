import type { ReactNode } from "react";
import type { SeverityKey } from "@ads-os/tokens";
import { cn } from "../lib/cn";
import { Button } from "./Button";
import { SeverityBadge } from "./StatusBadge";
import { formatRelativeTime } from "../lib/format";
import { IconAlert, IconCritical, IconIdea, IconInfo } from "../icons";

const severityIcon: Record<SeverityKey, typeof IconInfo> = {
  critical: IconCritical,
  warning: IconAlert,
  recommendation: IconIdea,
  info: IconInfo,
};

export interface RecommendationCardProps {
  level: SeverityKey;
  title: string;
  /** Причина в 1–3 строки. Длинные AI-тексты в карточку не помещаются (v0.3 §126). */
  reason: string;
  /** Короткий список причин. Показывается вместо reason, если задан. */
  reasons?: string[];
  createdAt?: Date;
  /**
   * Момент отсчёта для «10 минут назад».
   *
   * Вынесен в параметр, чтобы возраст рекомендации был воспроизводимым: без
   * этого статически отрендеренная страница показывает время сборки, а не
   * время пользователя, и тесты становятся зависимыми от даты запуска.
   */
  now?: Date;
  /**
   * Действие требует подтверждения.
   *
   * Кнопка «Применить» тогда не выполняет изменение, а открывает approval flow:
   * никакое нажатие не является само по себе подтверждением рискованной
   * операции (v0.3 §88, §126).
   */
  requiresApproval?: boolean;
  onApply?: () => void;
  onDetails?: () => void;
  applying?: boolean;
  footer?: ReactNode;
  className?: string;
}

export function RecommendationCard({
  level,
  title,
  reason,
  reasons,
  createdAt,
  now,
  requiresApproval = false,
  onApply,
  onDetails,
  applying = false,
  footer,
  className,
}: RecommendationCardProps) {
  const Icon = severityIcon[level];

  return (
    <article
      className={cn(
        "border-border hover:bg-surface-hover rounded-small-card border p-4",
        "transition-colors duration-(--duration-fast) ease-out",
        className,
      )}
    >
      <div className="mb-2 flex items-start justify-between gap-4">
        <SeverityBadge level={level} icon={<Icon size={12} />} />
        {createdAt && (
          <span className="text-micro text-text-secondary shrink-0">
            {formatRelativeTime(createdAt, now)}
          </span>
        )}
      </div>

      <h3 className="text-body-sm text-text-primary mb-1 font-semibold">{title}</h3>

      {reasons?.length ? (
        <ul className="text-caption text-text-secondary mb-3 flex list-none flex-col gap-0.5">
          {reasons.map((item) => (
            <li key={item} className="flex gap-1.5">
              <span aria-hidden="true">•</span>
              <span>{item}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-caption text-text-secondary mb-3">{reason}</p>
      )}

      <div className="flex flex-wrap items-center gap-2">
        {onApply && (
          <Button size="sm" onClick={onApply} loading={applying}>
            {requiresApproval ? "На согласование" : "Применить"}
          </Button>
        )}
        {onDetails && (
          <Button size="sm" variant="secondary" onClick={onDetails}>
            Подробнее
          </Button>
        )}
        {footer}
      </div>
    </article>
  );
}
