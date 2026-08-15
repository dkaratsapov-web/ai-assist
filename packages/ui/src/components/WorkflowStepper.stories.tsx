import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { lifecycleSteps } from "@ads-os/tokens";
import { WorkflowStepper, type WorkflowStep } from "./WorkflowStepper";

const build = (states: WorkflowStep["state"][]): WorkflowStep[] =>
  lifecycleSteps.map((step, index) => ({
    key: step.key,
    label: step.label,
    description: step.description,
    state: states[index] ?? "waiting",
  }));

const meta = {
  title: "Проект/WorkflowStepper",
  component: WorkflowStepper,
  decorators: [
    (Story) => (
      <div className="bg-surface rounded-card w-[1100px] p-4">
        <Story />
      </div>
    ),
  ],
} satisfies Meta<typeof WorkflowStepper>;

export default meta;
type Story = StoryObj<typeof meta>;

/**
 * Канонический жизненный цикл: десять шагов (v0.4 §3).
 *
 * Референс дашборда рисует восемь, но по правилу приоритета v0.4 §26 выигрывает
 * lifecycle. Лента прокручивается по горизонтали — это тот случай, когда
 * горизонтальный скролл предусмотрен намеренно.
 */
export const InProgress: Story = {
  args: {
    steps: build([
      "completed",
      "completed",
      "completed",
      "completed",
      "active",
      "waiting",
      "waiting",
      "waiting",
      "waiting",
      "waiting",
    ]),
  },
};

export const NotStarted: Story = { args: { steps: build(["active"]) } };

/** Блокирующая ошибка на этапе проверки: дальше двигаться нельзя. */
export const Blocked: Story = {
  args: {
    steps: build([
      "completed",
      "completed",
      "completed",
      "completed",
      "completed",
      "error",
      "blocked",
      "blocked",
      "waiting",
      "waiting",
    ]),
  },
};

export const Completed: Story = {
  args: { steps: build(Array(10).fill("completed") as WorkflowStep["state"][]) },
};
