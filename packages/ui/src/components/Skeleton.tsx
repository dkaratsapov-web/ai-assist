import { cn } from "../lib/cn";

export interface SkeletonProps {
  className?: string;
  /** Скругление под тип содержимого. */
  shape?: "text" | "control" | "card" | "circle";
}

const shapeClasses = {
  text: "h-4 rounded-md",
  control: "h-10 rounded-control",
  card: "h-24 rounded-card",
  circle: "rounded-full",
} as const;

/**
 * Skeleton вместо пустого экрана (v0.3 §137).
 *
 * Пульсация отключается при prefers-reduced-motion: в отличие от спиннера, это
 * оформление ожидания, а не единственный признак процесса.
 */
export function Skeleton({ className, shape = "text" }: SkeletonProps) {
  return (
    <div
      aria-hidden="true"
      className={cn(
        "bg-bg-secondary animate-pulse motion-reduce:animate-none",
        shapeClasses[shape],
        className,
      )}
    />
  );
}

export interface SkeletonTextProps {
  lines?: number;
  className?: string;
}

export function SkeletonText({ lines = 3, className }: SkeletonTextProps) {
  return (
    <div className={cn("flex flex-col gap-2", className)}>
      {Array.from({ length: lines }, (_, i) => (
        <Skeleton key={i} className={i === lines - 1 ? "w-3/5" : "w-full"} />
      ))}
    </div>
  );
}
