import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { EmptyState } from "./EmptyState";
import { ErrorState } from "./ErrorState";
import { Skeleton, SkeletonText } from "./Skeleton";
import { Card } from "./Card";
import { IconSparkles } from "../icons";

/**
 * Состояния экранов.
 *
 * Loading, empty и error — не «на потом»: экран без них считается недоделанным
 * (v0.3 §137, §150).
 */
const meta = {
  title: "Состояния/Empty, Error, Skeleton",
  component: EmptyState,
  args: { title: "Пока нет данных" },
  decorators: [
    (Story) => (
      <div className="w-[520px]">
        <Card>
          <Story />
        </Card>
      </div>
    ),
  ],
} satisfies Meta<typeof EmptyState>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Empty: Story = {
  args: {
    title: "Пока нет рекомендаций",
    description:
      "Система продолжает анализировать проект. Первые выводы появятся после сбора данных.",
    icon: <IconSparkles size={28} />,
    actionLabel: "Запустить анализ",
    onAction: () => undefined,
  },
};

export const Error: Story = {
  render: () => (
    <ErrorState
      title="Не удалось загрузить данные кампаний"
      description="Попробуйте повторить запрос. Если ошибка повторяется, передайте код обращения в поддержку."
      requestId="req_01JC8XN4K2QW"
      onRetry={() => undefined}
    />
  ),
};

/** Для сломанной интеграции повтор бесполезен — нужно переподключение. */
export const IntegrationError: Story = {
  render: () => (
    <ErrorState
      title="Доступ к Яндекс Директу отозван"
      description="Токен интеграции больше не действителен, данные не обновляются."
      requestId="req_01JC8XN51PBD"
      onReconnect={() => undefined}
    />
  ),
};

export const Loading: Story = {
  render: () => (
    <div className="flex flex-col gap-4">
      <Skeleton className="h-4 w-40" />
      <Skeleton shape="control" />
      <SkeletonText lines={3} />
      <Skeleton shape="card" />
    </div>
  ),
};
