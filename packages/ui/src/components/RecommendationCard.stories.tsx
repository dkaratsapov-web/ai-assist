import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { RecommendationCard } from "./RecommendationCard";
import { AlertCard } from "./AlertCard";

const now = new Date("2026-05-07T12:00:00Z");

const meta = {
  title: "AI/RecommendationCard",
  component: RecommendationCard,
  args: {
    level: "critical",
    title: "Рост CPL в кампании «Ремонт iPhone»",
    reason: "CPL вырос на 32% за 3 дня.",
    createdAt: new Date(now.getTime() - 10 * 60_000),
    now,
    onApply: () => undefined,
    onDetails: () => undefined,
  },
  decorators: [
    (Story) => (
      <div className="bg-surface rounded-card w-96 p-2">
        <Story />
      </div>
    ),
  ],
} satisfies Meta<typeof RecommendationCard>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Critical: Story = {};

export const Warning: Story = {
  args: {
    level: "warning",
    title: "Добавить минус-фразы",
    reason: "Найдено 124 нерелевантных запроса, которые расходуют бюджет впустую.",
  },
};

export const Recommendation: Story = {
  args: {
    level: "recommendation",
    title: "Протестировать новый креатив",
    reason: "CTR может вырасти примерно на 18% по текущим данным.",
  },
};

export const Info: Story = {
  args: {
    level: "info",
    title: "Анализ конкурентов завершён",
    reason: "Обработано 12 доменов, найдено 8 активных офферов.",
    onApply: undefined,
  },
};

/** Список причин вместо сплошного текста — читается быстрее. */
export const WithReasonList: Story = {
  args: {
    reasons: ["нерелевантные поисковые запросы", "снижение конверсии посадочной страницы"],
  },
};

/**
 * Действие требует согласования.
 *
 * Кнопка меняет подпись: пользователь должен понимать, что нажатие не выполнит
 * изменение немедленно (v0.3 §88).
 */
export const RequiresApproval: Story = { args: { requiresApproval: true } };

export const Applying: Story = { args: { applying: true } };

export const Alerts: Story = {
  render: () => (
    <div className="divide-border flex flex-col divide-y">
      {(["critical", "warning", "recommendation", "info"] as const).map((level) => (
        <AlertCard
          key={level}
          level={level}
          message="Рост CPL в кампании «Ремонт iPhone»"
          createdAt={new Date(now.getTime() - 60 * 60_000)}
          now={now}
        />
      ))}
    </div>
  ),
};
