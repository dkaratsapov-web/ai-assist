import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { Button, IconButton } from "./Button";
import { IconPlus, IconClose, IconArrowRight } from "../icons";

const meta = {
  title: "Примитивы/Button",
  component: Button,
  args: { children: "Применить" },
} satisfies Meta<typeof Button>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Primary: Story = {};

export const Secondary: Story = { args: { variant: "secondary" } };

export const Ghost: Story = { args: { variant: "ghost", children: "Подробнее" } };

/** Для необратимых и денежных действий. Используется в ConfirmationDialog. */
export const Critical: Story = { args: { variant: "critical", children: "Отключить кампанию" } };

/**
 * Все состояния разом.
 *
 * Отдельно проверяется loading: кнопка обязана блокироваться, иначе повторное
 * нажатие выполнит действие дважды (v0.3 §113).
 */
export const States: Story = {
  render: () => (
    <div className="flex flex-col gap-4">
      {(["primary", "secondary", "ghost", "critical"] as const).map((variant) => (
        <div key={variant} className="flex flex-wrap items-center gap-2">
          <Button variant={variant}>Обычная</Button>
          <Button variant={variant} loading>
            Выполняется
          </Button>
          <Button variant={variant} disabled>
            Недоступна
          </Button>
        </div>
      ))}
    </div>
  ),
};

export const Sizes: Story = {
  render: () => (
    <div className="flex flex-wrap items-center gap-2">
      <Button size="sm">Маленькая</Button>
      <Button size="md">Средняя</Button>
      <Button size="lg">Большая</Button>
    </div>
  ),
};

export const WithIcons: Story = {
  render: () => (
    <div className="flex flex-wrap items-center gap-2">
      <Button iconLeft={<IconPlus size={16} />}>Новый проект</Button>
      <Button variant="secondary" iconRight={<IconArrowRight size={16} />}>
        Подробнее
      </Button>
      <IconButton label="Закрыть" icon={<IconClose size={18} />} variant="ghost" />
    </div>
  ),
};
