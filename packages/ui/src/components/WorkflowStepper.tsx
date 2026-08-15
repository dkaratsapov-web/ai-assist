import type { Tone, WorkflowStepStateKey } from "@ads-os/tokens";
import { workflowStepState } from "@ads-os/tokens";
import { cn } from "../lib/cn";
import { toneClasses } from "../lib/tone";
import { IconCheckCircle, IconClock, IconCritical, IconLock, IconSparkles } from "../icons";

export interface WorkflowStep {
  key: string;
  label: string;
  description?: string;
  state: WorkflowStepStateKey;
}

export interface WorkflowStepperProps {
  steps: WorkflowStep[];
  onStepClick?: (key: string) => void;
  className?: string;
}

const stateIcon: Record<WorkflowStepStateKey, typeof IconClock> = {
  completed: IconCheckCircle,
  active: IconSparkles,
  waiting: IconClock,
  blocked: IconLock,
  error: IconCritical,
};

/**
 * Цепочка этапов проекта.
 *
 * Десять шагов канонического жизненного цикла (v0.4 §3). Референс дашборда
 * рисует восемь, но по правилу приоритета v0.4 §26 выигрывает lifecycle;
 * поэтому цепочка компактная и прокручивается по горизонтали — это тот случай,
 * когда горизонтальный скролл предусмотрен намеренно (v0.3 §150).
 */
export function WorkflowStepper({ steps, onStepClick, className }: WorkflowStepperProps) {
  return (
    <ol
      className={cn(
        "flex snap-x snap-mandatory list-none gap-3 overflow-x-auto pb-2",
        "[scrollbar-width:thin]",
        className,
      )}
    >
      {steps.map((step, index) => {
        const entry = workflowStepState[step.state];
        const tone = entry.tone as Tone;
        const Icon = stateIcon[step.state];
        const Root = onStepClick ? "button" : "div";

        return (
          <li key={step.key} className="flex shrink-0 snap-start items-center">
            <Root
              {...(onStepClick
                ? { type: "button" as const, onClick: () => onStepClick(step.key) }
                : {})}
              aria-current={step.state === "active" ? "step" : undefined}
              className={cn(
                "border-border rounded-small-card flex h-full w-44 flex-col items-start gap-1.5 border p-3 text-left",
                step.state === "active" && "border-border-strong bg-bg-secondary",
                step.state === "waiting" && "opacity-70",
                onStepClick &&
                  "hover:bg-surface-hover focus-visible:outline-focus cursor-pointer focus-visible:outline-2 focus-visible:outline-offset-2",
                "transition-colors duration-(--duration-fast) ease-out",
              )}
            >
              <span className="text-micro text-text-secondary flex items-center gap-1.5 font-medium">
                <span
                  aria-hidden="true"
                  className="border-border text-text-secondary flex size-4 items-center justify-center rounded-full border text-[10px]"
                >
                  {index + 1}
                </span>
                Шаг {index + 1}
              </span>

              <span className="text-body-sm text-text-primary font-semibold">{step.label}</span>

              {step.description && (
                <span className="text-micro text-text-secondary line-clamp-3 leading-snug">
                  {step.description}
                </span>
              )}

              <span
                className={cn(
                  "text-micro mt-auto flex items-center gap-1 pt-1 font-medium",
                  toneClasses[tone].text,
                )}
              >
                <Icon size={13} aria-hidden="true" />
                {entry.label}
              </span>
            </Root>

            {index < steps.length - 1 && (
              <span aria-hidden="true" className="text-text-disabled px-1.5 select-none">
                →
              </span>
            )}
          </li>
        );
      })}
    </ol>
  );
}
