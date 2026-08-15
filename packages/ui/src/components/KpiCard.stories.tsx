import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { KpiCard } from "./KpiCard";

const meta = {
  title: "Данные/KpiCard",
  component: KpiCard,
  args: {
    label: "Расходы",
    value: "142 750 ₽",
    delta: 12,
    polarity: "neutral",
    period: "за 7 дней",
    trend: [88, 96, 91, 104, 99, 118, 131, 142],
  },
  decorators: [
    (Story) => (
      <div className="w-64">
        <Story />
      </div>
    ),
  ],
} satisfies Meta<typeof KpiCard>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};

export const Loading: Story = { args: { loading: true } };

/**
 * Метрика посчитана по временному заменителю.
 *
 * Так выглядит показатель в Limited Economics Mode (v0.4 §5): экономика не
 * заполнена, поэтому вместо достоверного CAC показывается оценка.
 */
export const Proxy: Story = {
  args: {
    label: "CAC",
    value: "2 460 ₽",
    delta: -4,
    polarity: "up-is-bad",
    availability: "proxy",
    availabilityHint: "Считается по CPL: не заполнена конверсия из лида в продажу",
  },
};

/**
 * Источник данных не подключён.
 *
 * До подключения CRM выручка и ROAS недостоверны, поэтому число не рисуется
 * вовсе — правдоподобная цифра здесь хуже честного пробела (решение B в
 * v0.4-decisions).
 */
export const Unavailable: Story = {
  args: {
    label: "Выручка",
    value: "—",
    availability: "unavailable",
    availabilityHint: "Подключите CRM, чтобы видеть выручку и ROAS",
    trend: undefined,
    delta: undefined,
  },
};

export const Row: Story = {
  decorators: [
    (Story) => (
      <div className="w-[1000px]">
        <Story />
      </div>
    ),
  ],
  render: () => (
    <div className="grid grid-cols-4 gap-4">
      <KpiCard
        label="Расходы"
        value="142 750 ₽"
        delta={12}
        polarity="neutral"
        period="за 7 дней"
        trend={[88, 96, 91, 104, 99, 118, 142]}
      />
      <KpiCard
        label="Лиды"
        value="267"
        delta={18}
        polarity="up-is-good"
        period="за 7 дней"
        trend={[180, 195, 188, 214, 238, 251, 267]}
        seriesColor="var(--color-chart-2)"
      />
      <KpiCard
        label="CPL"
        value="535 ₽"
        delta={-7}
        polarity="up-is-bad"
        period="за 7 дней"
        trend={[612, 598, 578, 566, 551, 542, 535]}
        seriesColor="var(--color-chart-4)"
      />
      <KpiCard
        label="Продажи"
        value="58"
        delta={11}
        polarity="up-is-good"
        period="за 7 дней"
        trend={[38, 41, 44, 46, 49, 52, 58]}
        seriesColor="var(--color-chart-3)"
      />
    </div>
  ),
};
