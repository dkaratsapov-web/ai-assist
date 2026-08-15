import type { SeverityKey, Tone } from "@ads-os/tokens";
import { severity as severityVocabulary } from "@ads-os/tokens";
import { cn } from "../lib/cn";
import { toneClasses } from "../lib/tone";
import { formatRelativeTime } from "../lib/format";
import { IconAlert, IconCritical, IconIdea, IconInfo } from "../icons";

const severityIcon: Record<SeverityKey, typeof IconInfo> = {
  critical: IconCritical,
  warning: IconAlert,
  recommendation: IconIdea,
  info: IconInfo,
};

export interface AlertCardProps {
  level: SeverityKey;
  message: string;
  createdAt?: Date;
  /** Момент отсчёта для относительного времени. См. RecommendationCard. */
  now?: Date;
  onClick?: () => void;
  className?: string;
}

/**
 * Строка уведомления.
 *
 * Критический алерт не мигает и не использует стрессовую анимацию (v0.3 §122):
 * внимание привлекается подписью, иконкой и цветом точки, а не движением.
 */
export function AlertCard({ level, message, createdAt, now, onClick, className }: AlertCardProps) {
  const entry = severityVocabulary[level];
  const tone = entry.tone as Tone;
  const Icon = severityIcon[level];
  const Root = onClick ? "button" : "div";

  return (
    <Root
      {...(onClick ? { type: "button" as const, onClick } : {})}
      className={cn(
        "flex w-full items-start gap-3 py-2.5 text-left",
        onClick &&
          "rounded-control focus-visible:outline-focus -mx-2 cursor-pointer px-2 focus-visible:outline-2 focus-visible:outline-offset-2",
        onClick && "hover:bg-surface-hover transition-colors duration-(--duration-fast) ease-out",
        className,
      )}
    >
      <span className={cn("mt-0.5 shrink-0", toneClasses[tone].text)}>
        <Icon size={16} />
      </span>

      <span className="min-w-0 flex-1">
        <span className="text-caption text-text-primary block">
          <span className={cn("font-medium", toneClasses[tone].text)}>{entry.label}:</span>{" "}
          {message}
        </span>
      </span>

      {createdAt && (
        <span className="text-micro text-text-secondary shrink-0 whitespace-nowrap">
          {formatRelativeTime(createdAt, now)}
        </span>
      )}
    </Root>
  );
}
