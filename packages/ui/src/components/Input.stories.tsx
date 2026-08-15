import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { Input, SearchInput } from "./Input";

const meta = {
  title: "Примитивы/Input",
  component: Input,
  args: { label: "Целевой CPL", placeholder: "Например, 500" },
  decorators: [
    (Story) => (
      <div className="w-80">
        <Story />
      </div>
    ),
  ],
} satisfies Meta<typeof Input>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};

export const WithHint: Story = {
  args: { hint: "Используется для оценки эффективности кампаний" },
};

/** Ошибка передаётся текстом и через aria-invalid, а не только цветом рамки. */
export const WithError: Story = {
  args: { error: "Значение должно быть больше нуля", defaultValue: "-100" },
};

export const Disabled: Story = { args: { disabled: true, defaultValue: "500" } };

export const Search: Story = {
  render: () => <SearchInput placeholder="Поиск по проектам…" shortcut="⌘K" aria-label="Поиск" />,
};
