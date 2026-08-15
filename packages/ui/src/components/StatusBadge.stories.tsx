import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import {
  StatusBadge,
  SeverityBadge,
  ProjectStatusBadge,
  ModuleStatusBadge,
  IntegrationStatusBadge,
} from "./StatusBadge";
import { MetricTrend } from "./MetricTrend";

const meta = {
  title: "Статусы/StatusBadge",
  component: StatusBadge,
  args: { children: "Активен" },
} satisfies Meta<typeof StatusBadge>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Tones: Story = {
  render: () => (
    <div className="flex flex-wrap gap-2">
      <StatusBadge tone="success">Успех</StatusBadge>
      <StatusBadge tone="warning">Предупреждение</StatusBadge>
      <StatusBadge tone="critical">Критично</StatusBadge>
      <StatusBadge tone="info">Информация</StatusBadge>
      <StatusBadge tone="neutral">Нейтрально</StatusBadge>
    </div>
  ),
};

/**
 * Бейджи, читающие подпись из словаря токенов.
 *
 * Один и тот же словарь используют Web и сообщения ботов, поэтому «Критично»
 * в интерфейсе и в Telegram — гарантированно одно и то же слово (v0.4 §19).
 */
export const FromVocabulary: Story = {
  render: () => (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap gap-2">
        {(["critical", "warning", "recommendation", "info"] as const).map((level) => (
          <SeverityBadge key={level} level={level} dot />
        ))}
      </div>
      <div className="flex flex-wrap gap-2">
        {(["draft", "active", "paused", "archived", "error"] as const).map((status) => (
          <ProjectStatusBadge key={status} status={status} dot />
        ))}
      </div>
      <div className="flex flex-wrap gap-2">
        {(["not_started", "queued", "running", "needs_review", "completed", "failed"] as const).map(
          (status) => (
            <ModuleStatusBadge key={status} status={status} />
          ),
        )}
      </div>
      <div className="flex flex-wrap gap-2">
        {(["connected", "degraded", "disconnected", "error"] as const).map((status) => (
          <IntegrationStatusBadge key={status} status={status} dot />
        ))}
      </div>
    </div>
  ),
};

/**
 * Направление динамики и её оценка — разные вещи.
 *
 * Рост выручки — успех, рост CPL — проблема. Поэтому окраска задаётся
 * параметром polarity, а не знаком числа.
 */
export const Trends: Story = {
  render: () => (
    <div className="flex flex-col gap-2">
      <span className="text-caption text-text-secondary">
        Выручка +15% (рост — хорошо): <MetricTrend delta={15} polarity="up-is-good" />
      </span>
      <span className="text-caption text-text-secondary">
        CPL +32% (рост — плохо): <MetricTrend delta={32} polarity="up-is-bad" />
      </span>
      <span className="text-caption text-text-secondary">
        CPL −7% (снижение — хорошо): <MetricTrend delta={-7} polarity="up-is-bad" />
      </span>
      <span className="text-caption text-text-secondary">
        Расходы +12% (оценка не задана): <MetricTrend delta={12} polarity="neutral" />
      </span>
    </div>
  ),
};
