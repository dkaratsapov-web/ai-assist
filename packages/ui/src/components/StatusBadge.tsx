import type { HTMLAttributes, ReactNode } from "react";
import {
  integrationStatus,
  moduleStatus,
  projectStatus,
  severity,
  type IntegrationStatusKey,
  type ModuleStatusKey,
  type ProjectStatusKey,
  type SeverityKey,
  type Tone,
} from "@ads-os/tokens";
import { cn } from "../lib/cn";
import { toneClasses } from "../lib/tone";

export interface StatusBadgeProps extends Omit<HTMLAttributes<HTMLSpanElement>, "children"> {
  tone?: Tone;
  /** Точка-индикатор слева. Дублирует тон, но помогает при слабом различении цвета. */
  dot?: boolean;
  icon?: ReactNode;
  size?: "sm" | "md";
  children: ReactNode;
}

/**
 * Бейдж статуса.
 *
 * Текстовая подпись обязательна — она передаётся через children и является
 * основным носителем смысла. Цвет и точка только усиливают её (v0.3 §139).
 */
export function StatusBadge({
  tone = "neutral",
  dot = false,
  icon,
  size = "sm",
  className,
  children,
  ...rest
}: StatusBadgeProps) {
  return (
    <span
      {...rest}
      className={cn(
        "rounded-pill inline-flex items-center gap-1.5 border font-medium whitespace-nowrap",
        size === "sm" ? "text-micro px-2 py-0.5" : "text-caption px-2.5 py-1",
        toneClasses[tone].badge,
        className,
      )}
    >
      {dot && (
        <span aria-hidden="true" className={cn("size-1.5 rounded-full", toneClasses[tone].dot)} />
      )}
      {icon}
      {children}
    </span>
  );
}

/* ── Бейджи, читающие подпись и тон из словаря токенов ─────────────────────── */

export function SeverityBadge({
  level,
  ...props
}: { level: SeverityKey } & Omit<StatusBadgeProps, "tone" | "children">) {
  const entry = severity[level];
  return (
    <StatusBadge tone={entry.tone as Tone} {...props}>
      {entry.label}
    </StatusBadge>
  );
}

export function ProjectStatusBadge({
  status,
  ...props
}: { status: ProjectStatusKey } & Omit<StatusBadgeProps, "tone" | "children">) {
  const entry = projectStatus[status];
  return (
    <StatusBadge tone={entry.tone as Tone} {...props}>
      {entry.label}
    </StatusBadge>
  );
}

export function ModuleStatusBadge({
  status,
  ...props
}: { status: ModuleStatusKey } & Omit<StatusBadgeProps, "tone" | "children">) {
  const entry = moduleStatus[status];
  return (
    <StatusBadge tone={entry.tone as Tone} {...props}>
      {entry.label}
    </StatusBadge>
  );
}

export function IntegrationStatusBadge({
  status,
  ...props
}: { status: IntegrationStatusKey } & Omit<StatusBadgeProps, "tone" | "children">) {
  const entry = integrationStatus[status];
  return (
    <StatusBadge tone={entry.tone as Tone} {...props}>
      {entry.label}
    </StatusBadge>
  );
}
