import type { ReactNode } from "react";
import { cn } from "../lib/cn";
import { Button } from "./Button";

export interface EmptyStateProps {
  /** Что именно пусто. Короткая фраза, не заголовок раздела. */
  title: string;
  /** Почему данных нет и что произойдёт дальше. */
  description?: string;
  icon?: ReactNode;
  actionLabel?: string;
  onAction?: () => void;
  className?: string;
}

/**
 * Пустое состояние.
 *
 * Обязано объяснить, почему здесь пока нет данных и что сделать дальше
 * (v0.3 §137). Пустой экран без объяснения считается недоделанным.
 */
export function EmptyState({
  title,
  description,
  icon,
  actionLabel,
  onAction,
  className,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-3 px-4 py-8 text-center",
        className,
      )}
    >
      {icon && <span className="text-text-disabled">{icon}</span>}
      <p className="text-body-sm text-text-primary font-medium">{title}</p>
      {description && <p className="text-caption text-text-secondary max-w-sm">{description}</p>}
      {actionLabel && onAction && (
        <Button size="sm" variant="secondary" onClick={onAction} className="mt-1">
          {actionLabel}
        </Button>
      )}
    </div>
  );
}
