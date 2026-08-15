"use client";

import { useEffect, useState, type ReactNode } from "react";
import { cn } from "../lib/cn";
import { Button } from "./Button";
import { Modal } from "./Modal";
import { StatusBadge } from "./StatusBadge";
import { formatNumber, plural } from "../lib/format";
import { IconArrowRight } from "../icons";

export interface ChangePreview {
  label: string;
  /** Значение до изменения. */
  before: string;
  /** Значение после изменения. */
  after: string;
}

export interface ConfirmationDialogProps {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void;
  /** Что именно произойдёт. Формулируется действием, а не «Вы уверены?». */
  title: string;
  /** Последствия простым языком. */
  description?: string;
  /** Пары «было → станет». Обязательны для денежных и разрушающих действий. */
  changes?: ChangePreview[];
  /** Сколько сущностей затронет массовое действие. */
  affectedCount?: number;
  affectedNoun?: [one: string, few: string, many: string];
  confirmLabel?: string;
  cancelLabel?: string;
  /** Действие необратимо или расходует деньги — подтверждение красное. */
  destructive?: boolean;
  /**
   * Абсолютный момент истечения подтверждения — когда срок назначает backend.
   *
   * Подтверждение имеет TTL: после изменения исходных данных или по истечении
   * срока оно должно инвалидироваться, а не выполняться позже (v0.3 §88, §113).
   */
  expiresAt?: Date;
  /**
   * Относительный срок в миллисекундах — отсчитывается от момента открытия
   * диалога.
   *
   * Существует отдельно от `expiresAt`, чтобы вызывающий код не вычислял
   * дедлайн во время рендера: там `Date.now()` пересчитывался бы при каждой
   * перерисовке, срок уезжал бы вперёд и подтверждение не истекало бы никогда.
   */
  ttlMs?: number;
  busy?: boolean;
  children?: ReactNode;
}

/**
 * Единый диалог подтверждения для критических действий.
 *
 * Требования v0.3 §113 реализованы буквально: показывается точное действие и его
 * последствия, для бюджета — текущее и новое значение, для массовой операции —
 * количество затронутых сущностей. Кнопки разнесены по назначению, повторное
 * нажатие заблокировано на время выполнения, просроченное подтверждение
 * выполнить нельзя.
 */
export function ConfirmationDialog({
  open,
  onClose,
  onConfirm,
  title,
  description,
  changes,
  affectedCount,
  affectedNoun = ["сущность", "сущности", "сущностей"],
  confirmLabel = "Подтвердить",
  cancelLabel = "Отменить",
  destructive = false,
  expiresAt,
  ttlMs,
  busy = false,
  children,
}: ConfirmationDialogProps) {
  const expired = useExpiry(expiresAt, ttlMs, open);

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={title}
      description={description}
      size="sm"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            {cancelLabel}
          </Button>
          <Button
            variant={destructive ? "critical" : "primary"}
            onClick={onConfirm}
            loading={busy}
            disabled={expired}
          >
            {confirmLabel}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        {affectedCount !== undefined && (
          <StatusBadge
            tone={affectedCount > 20 ? "warning" : "neutral"}
            size="md"
            className="self-start"
          >
            Затронет {formatNumber(affectedCount)} {plural(affectedCount, ...affectedNoun)}
          </StatusBadge>
        )}

        {changes && changes.length > 0 && (
          <dl className="border-border rounded-small-card divide-border divide-y border">
            {changes.map((change) => (
              <div key={change.label} className="flex items-center justify-between gap-4 p-3">
                <dt className="text-caption text-text-secondary">{change.label}</dt>
                <dd className="text-body-sm text-text-primary flex items-center gap-2 font-medium tabular-nums">
                  <span className="text-text-secondary line-through decoration-1">
                    {change.before}
                  </span>
                  <IconArrowRight size={14} aria-hidden="true" />
                  <span>{change.after}</span>
                </dd>
              </div>
            ))}
          </dl>
        )}

        {children}

        {expired && (
          <p className="text-caption text-critical" role="alert">
            Срок действия подтверждения истёк. Закройте окно и запросите действие заново — за это
            время данные могли измениться.
          </p>
        )}
      </div>
    </Modal>
  );
}

/**
 * Следит за истечением TTL подтверждения, пока диалог открыт.
 *
 * Отсчёт запускается в эффекте, то есть после открытия диалога, а не во время
 * рендера: только так дедлайн фиксируется один раз и действительно наступает.
 */
function useExpiry(expiresAt: Date | undefined, ttlMs: number | undefined, open: boolean): boolean {
  const [expired, setExpired] = useState(false);

  useEffect(() => {
    if (!open || (!expiresAt && ttlMs === undefined)) {
      setExpired(false);
      return;
    }

    const deadline = expiresAt ? expiresAt.getTime() : Date.now() + (ttlMs ?? 0);
    const remaining = deadline - Date.now();

    if (remaining <= 0) {
      setExpired(true);
      return;
    }

    setExpired(false);
    const timer = setTimeout(() => setExpired(true), remaining);
    return () => clearTimeout(timer);
  }, [expiresAt, ttlMs, open]);

  return expired;
}
