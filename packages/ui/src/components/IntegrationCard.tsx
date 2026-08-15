import type { ReactNode } from "react";
import type { IntegrationStatusKey, Tone } from "@ads-os/tokens";
import { integrationStatus } from "@ads-os/tokens";
import { cn } from "../lib/cn";
import { toneClasses } from "../lib/tone";

export interface IntegrationCardProps {
  name: string;
  status: IntegrationStatusKey;
  /** Значок сервиса. Монохромный, как и остальные иконки. */
  icon: ReactNode;
  onClick?: () => void;
  className?: string;
}

/**
 * Плитка интеграции.
 *
 * Статус показывается точкой и подписью одновременно: по одному лишь цвету
 * точки состояние определять нельзя (v0.3 §139).
 */
export function IntegrationCard({ name, status, icon, onClick, className }: IntegrationCardProps) {
  const entry = integrationStatus[status];
  const tone = entry.tone as Tone;
  const Root = onClick ? "button" : "div";

  return (
    <Root
      {...(onClick ? { type: "button" as const, onClick } : {})}
      className={cn(
        "border-border rounded-small-card flex flex-col items-center gap-2 border p-3 text-center",
        onClick &&
          "hover:bg-surface-hover focus-visible:outline-focus cursor-pointer focus-visible:outline-2 focus-visible:outline-offset-2",
        "transition-colors duration-(--duration-fast) ease-out",
        className,
      )}
    >
      <span className="text-text-primary flex size-9 items-center justify-center">{icon}</span>
      <span className="text-micro text-text-primary leading-tight font-medium">{name}</span>
      <span className="text-micro text-text-secondary flex items-center gap-1">
        <span aria-hidden="true" className={cn("size-1.5 rounded-full", toneClasses[tone].dot)} />
        {entry.label}
      </span>
    </Root>
  );
}
