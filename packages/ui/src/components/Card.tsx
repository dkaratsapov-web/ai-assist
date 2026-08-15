import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "../lib/cn";

export type CardPadding = "none" | "sm" | "md" | "lg";
export type CardRadius = "small-card" | "card" | "hero-card";

export interface CardProps extends HTMLAttributes<HTMLDivElement> {
  padding?: CardPadding;
  radius?: CardRadius;
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
  interactive = false,
  className,
  children,
  ...props
}: CardProps) {
  return (
    <div
      className={cn(
        "bg-surface border-border shadow-card border",
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
    <div className={cn("mb-4 flex items-start justify-between gap-4", className)}>
      <div className="min-w-0">
        <h2 className="text-h3 text-text-primary truncate">{title}</h2>
        {description && <p className="text-caption text-text-secondary mt-1">{description}</p>}
      </div>
      {action && <div className="flex shrink-0 items-center gap-2">{action}</div>}
    </div>
  );
}
