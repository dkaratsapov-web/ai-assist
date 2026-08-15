import { useState } from "react";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { ConfirmationDialog } from "./ConfirmationDialog";
import { Button } from "./Button";

/**
 * Единый диалог подтверждения для критических действий.
 *
 * Требования v0.3 §113 реализованы буквально: точное действие и последствия,
 * для бюджета — было и станет, для массовой операции — количество затронутых
 * сущностей, TTL у подтверждения.
 */
const meta = {
  title: "Безопасность/ConfirmationDialog",
  component: ConfirmationDialog,
  args: {
    open: false,
    onClose: () => undefined,
    onConfirm: () => undefined,
    title: "Снизить дневной бюджет",
  },
} satisfies Meta<typeof ConfirmationDialog>;

export default meta;
type Story = StoryObj<typeof meta>;

function Demo(props: Partial<React.ComponentProps<typeof ConfirmationDialog>>) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button onClick={() => setOpen(true)}>Открыть диалог</Button>
      <ConfirmationDialog
        open={open}
        onClose={() => setOpen(false)}
        onConfirm={() => setOpen(false)}
        title="Снизить дневной бюджет"
        description="Действие затрагивает рекламный бюджет и выполняется только после подтверждения."
        confirmLabel="Подтвердить"
        {...props}
      />
    </>
  );
}

export const BudgetChange: Story = {
  render: () => (
    <Demo
      changes={[
        { label: "Дневной бюджет кампании", before: "4 500 ₽", after: "3 800 ₽" },
        { label: "Месячный прогноз расхода", before: "135 000 ₽", after: "114 000 ₽" },
      ]}
    />
  ),
};

/** Массовое действие: количество затронутых сущностей обязательно. */
export const MassAction: Story = {
  render: () => (
    <Demo
      title="Добавить минус-фразы"
      affectedCount={124}
      affectedNoun={["ключевая фраза", "ключевые фразы", "ключевых фраз"]}
      changes={[{ label: "Активных ключевых фраз", before: "1 284", after: "1 160" }]}
    />
  ),
};

export const Destructive: Story = {
  render: () => (
    <Demo
      title="Отключить кампанию «Ремонт iPhone»"
      description="Показы остановятся немедленно. Статистика и настройки сохранятся."
      confirmLabel="Отключить"
      destructive
      affectedCount={1}
      affectedNoun={["кампания", "кампании", "кампаний"]}
    />
  ),
};

/** Дата в прошлом задана константой, а не вычисляется в рендере. */
const alreadyExpired = new Date(0);

/**
 * Просроченное подтверждение.
 *
 * За время, пока диалог открыт, исходные данные могли измениться — выполнять
 * такое действие нельзя, кнопка блокируется.
 */
export const Expired: Story = {
  render: () => (
    <Demo
      expiresAt={alreadyExpired}
      changes={[{ label: "Дневной бюджет кампании", before: "4 500 ₽", after: "3 800 ₽" }]}
    />
  ),
};

export const Busy: Story = {
  render: () => (
    <Demo busy changes={[{ label: "Дневной бюджет", before: "4 500 ₽", after: "3 800 ₽" }]} />
  ),
};
