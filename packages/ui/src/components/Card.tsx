import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "../lib/cn";

export type CardPadding = "none" | "sm" | "md" | "lg";
export type CardRadius = "small-card" | "card" | "hero-card";
export type CardTone = "default" | "quiet";

export interface CardProps extends HTMLAttributes<HTMLDivElement> {
  padding?: CardPadding;
  radius?: CardRadius;
  /**
   * Вес карточки.
   *
   * `quiet` — для пояснений, оговорок и вспомогательных блоков: без тени и
   * почти без границы, на общем фоне. Раньше такие блоки верстались обычной
   * карточкой и получали тот же вес, что и данные, — экран превращался в
   * лестницу одинаковых белых прямоугольников, где ничто не главнее другого.
   */
  tone?: CardTone;
  /** Реакция на наведение. Включается только для кликабельных карточек. */
  interactive?: boolean;
}

const paddingClasses: Record<CardPadding, string> = {
  none: "",
  sm: "p-3",
  md: "p-4",
  lg: "p-6",
};

const radiusClasses: Record<CardRadius, string> = {
  "small-card": "rounded-small-card",
  card: "rounded-card",
  "hero-card": "rounded-hero-card",
};

const toneClasses: Record<CardTone, string> = {
  default: "bg-surface border-border shadow-card border",
  quiet: "bg-bg-secondary border-border-subtle border",
};

/**
 * Базовая поверхность.
 *
 * Граница намеренно светлая: карточка опознаётся фоном и мягкой тенью, а не
 * жирной рамкой (v0.3 §121). Рамки внутри рамок не допускаются — вложенность
 * показывается фоном и отступом.
 */
export function Card({
  padding = "md",
  radius = "card",
  tone = "default",
  interactive = false,
  className,
  children,
  ...props
}: CardProps) {
  return (
    <div
      className={cn(
        toneClasses[tone],
        radiusClasses[radius],
        paddingClasses[padding],
        interactive && "hover:shadow-raised transition-shadow duration-(--duration-fast) ease-out",
        className,
      )}
      {...props}
    >
      {children}
    </div>
  );
}

export interface CardHeaderProps {
  title: ReactNode;
  /** Действие справа: ссылка «Смотреть все», фильтр, кнопка. */
  action?: ReactNode;
  description?: ReactNode;
  className?: string;
}

export function CardHeader({ title, action, description, className }: CardHeaderProps) {
  return (
    <div className={cn("mb-3 flex items-start justify-between gap-4", className)}>
      <div className="min-w-0">
        <h2 className="text-h3 text-text-primary truncate">{title}</h2>
        {/* Длина строки ограничена: пояснение во всю ширину экрана глаз не
            удерживает — на обратном ходе он теряет место, и человек
            перечитывает. */}
        {description && (
          <p className="text-caption text-text-secondary mt-1 max-w-(--layout-measure)">
            {description}
          </p>
        )}
      </div>
      {action && <div className="flex shrink-0 items-center gap-2">{action}</div>}
    </div>
  );
}

export interface SectionProps {
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}

/**
 * Группа карточек под общим заголовком.
 *
 * Экран из десяти карточек подряд читается как список без начала и конца:
 * каждая следующая выглядит ровно так же важно, как предыдущая. Заголовок
 * секции возвращает уровень выше карточки и делает видимым, что здесь два-три
 * смысловых блока, а не десять равных.
 */
export function Section({ title, description, action, children, className }: SectionProps) {
  return (
    <section className={cn("flex flex-col gap-3", className)}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <div className="min-w-0">
          <h2 className="text-h3 text-text-primary">{title}</h2>
          {description && (
            <p className="text-caption text-text-secondary mt-0.5 max-w-(--layout-measure)">
              {description}
            </p>
          )}
        </div>
        {action && <div className="flex shrink-0 items-center gap-2">{action}</div>}
      </div>
      {children}
    </section>
  );
}
