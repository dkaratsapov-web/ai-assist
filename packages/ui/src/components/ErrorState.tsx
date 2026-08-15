import { cn } from "../lib/cn";
import { Button } from "./Button";
import { IconCritical } from "../icons";

export interface ErrorStateProps {
  /** Короткое объяснение на языке пользователя. Не текст исключения. */
  title: string;
  description?: string;
  /**
   * Технический идентификатор запроса.
   *
   * Показывается мелко и целиком, чтобы пользователь мог передать его в
   * поддержку. Stack trace при этом наружу не выходит (v0.3 §137).
   */
  requestId?: string;
  onRetry?: () => void;
  retryLabel?: string;
  /** Для ошибок интеграции — «Переподключить» вместо повтора. */
  onReconnect?: () => void;
  className?: string;
}

export function ErrorState({
  title,
  description,
  requestId,
  onRetry,
  retryLabel = "Повторить",
  onReconnect,
  className,
}: ErrorStateProps) {
  return (
    <div
      role="alert"
      className={cn(
        "flex flex-col items-center justify-center gap-3 px-4 py-8 text-center",
        className,
      )}
    >
      <span className="text-critical">
        <IconCritical size={24} />
      </span>
      <p className="text-body-sm text-text-primary font-medium">{title}</p>
      {description && <p className="text-caption text-text-secondary max-w-sm">{description}</p>}

      <div className="mt-1 flex flex-wrap items-center justify-center gap-2">
        {onRetry && (
          <Button size="sm" variant="secondary" onClick={onRetry}>
            {retryLabel}
          </Button>
        )}
        {onReconnect && (
          <Button size="sm" onClick={onReconnect}>
            Переподключить
          </Button>
        )}
      </div>

      {requestId && (
        <p className="text-micro text-text-secondary mt-1 font-mono">Код обращения: {requestId}</p>
      )}
    </div>
  );
}
