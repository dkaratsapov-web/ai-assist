import { cn } from "../lib/cn";

export interface SparklineProps {
  values: number[];
  /** Цвет линии. Значение берётся из палитры серий графиков (v0.4 §19). */
  color?: string;
  width?: number;
  height?: number;
  /** Точка на последнем значении — как на референсе дашборда. */
  showLastPoint?: boolean;
  className?: string;
}

/**
 * Мини-график в карточке KPI.
 *
 * Реализован как обычный SVG без библиотеки: форма тривиальна, а собственная
 * реализация даёт точный контроль над толщиной линии и цветом из токенов.
 *
 * Сам по себе он декоративен (aria-hidden): значение и динамика уже выведены
 * текстом в карточке, поэтому дублировать их для скринридера не нужно.
 */
export function Sparkline({
  values,
  color = "var(--color-chart-1)",
  width = 96,
  height = 36,
  showLastPoint = true,
  className,
}: SparklineProps) {
  if (values.length < 2) return null;

  const padding = 3;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;

  const points = values.map((value, index) => {
    const x = padding + (index / (values.length - 1)) * (width - padding * 2);
    const y = height - padding - ((value - min) / span) * (height - padding * 2);
    return [x, y] as const;
  });

  const path = points
    .map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`)
    .join(" ");
  const last = points[points.length - 1];

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      fill="none"
      aria-hidden="true"
      className={cn("overflow-visible", className)}
    >
      <path
        d={path}
        stroke={color}
        strokeWidth={1.75}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {showLastPoint && last && <circle cx={last[0]} cy={last[1]} r={2.75} fill={color} />}
    </svg>
  );
}
