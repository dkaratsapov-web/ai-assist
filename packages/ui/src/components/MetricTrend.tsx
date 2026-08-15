import { cn } from "../lib/cn";
import { formatDelta } from "../lib/format";
import { IconArrowDown, IconArrowUp } from "../icons";

/**
 * Как трактовать рост метрики.
 *
 * Отдельный параметр нужен потому, что направление само по себе не говорит,
 * хорошо это или плохо: рост выручки — успех, рост CPL — проблема. Ошибка
 * здесь означает зелёную стрелку на ухудшении, поэтому значение обязательное.
 */
export type MetricPolarity = "up-is-good" | "up-is-bad" | "neutral";

export interface MetricTrendProps {
  /** Изменение в процентах: 12 → +12%, -7 → −7%. */
  delta: number;
  polarity: MetricPolarity;
  /** Период сравнения, например «за 7 дней». */
  period?: string;
  size?: "sm" | "md";
  className?: string;
}

export function MetricTrend({ delta, polarity, period, size = "sm", className }: MetricTrendProps) {
  const isUp = delta > 0;
  const isFlat = delta === 0;

  const tone = isFlat || polarity === "neutral" ? "neutral" : sentiment(isUp, polarity);
  const toneClass =
    tone === "good" ? "text-success" : tone === "bad" ? "text-critical" : "text-text-secondary";

  const Arrow = isUp ? IconArrowUp : IconArrowDown;
  const label = isFlat
    ? "без изменений"
    : `${isUp ? "рост" : "снижение"} на ${Math.abs(delta)} процентов, ${tone === "good" ? "положительная динамика" : tone === "bad" ? "отрицательная динамика" : "нейтрально"}`;

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 font-medium",
        size === "sm" ? "text-micro" : "text-caption",
        toneClass,
        className,
      )}
    >
      {/* Стрелка дублирует смысл направления формой, а не только цветом. */}
      {!isFlat && <Arrow size={size === "sm" ? 12 : 14} aria-hidden="true" />}
      <span className="sr-only">{label}</span>
      <span aria-hidden="true">{formatDelta(delta)}</span>
      {period && (
        <span className="text-text-secondary font-normal" aria-hidden="true">
          {period}
        </span>
      )}
    </span>
  );
}

function sentiment(isUp: boolean, polarity: MetricPolarity): "good" | "bad" | "neutral" {
  if (polarity === "neutral") return "neutral";
  const goodWhenUp = polarity === "up-is-good";
  return isUp === goodWhenUp ? "good" : "bad";
}
