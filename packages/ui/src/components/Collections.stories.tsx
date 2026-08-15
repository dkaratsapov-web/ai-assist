import { useState } from "react";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { DataTable, type DataTableColumn, type DataTableProps } from "./DataTable";
import { FilterBar } from "./FilterBar";
import { ProjectCard } from "./ProjectCard";
import { IntegrationCard } from "./IntegrationCard";
import { ProjectSwitcher } from "./ProjectSwitcher";
import { ChatComposer } from "./ChatComposer";
import { LineChart } from "./LineChart";
import { AiAvatar } from "./AiAvatar";
import { StatusBadge } from "./StatusBadge";
import { Card } from "./Card";
import { formatCurrency, formatNumber } from "../lib/format";
import { IconChart, IconTarget, IconUsers } from "../icons";

/**
 * DataTable — дженерик по типу строки, поэтому в meta он не указывается:
 * иначе Storybook выводит параметры по неизвестному Row и типы приходится
 * подавлять приведениями. Истории рендерятся явно.
 */
const meta: Meta = {
  title: "Коллекции/Списки и графики",
  decorators: [
    (Story) => (
      <div className="w-[860px]">
        <Story />
      </div>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof meta>;

interface QueryRow {
  query: string;
  clicks: number;
  spend: number;
  leads: number;
  verdict: "keep" | "negative" | "review";
}

const rows: QueryRow[] = [
  { query: "ремонт iphone тверь", clicks: 412, spend: 24_800, leads: 38, verdict: "keep" },
  { query: "ремонт iphone своими руками", clicks: 96, spend: 5_100, leads: 0, verdict: "negative" },
  { query: "замена экрана iphone 14", clicks: 208, spend: 13_600, leads: 21, verdict: "keep" },
  { query: "iphone ремонт вакансии", clicks: 34, spend: 1_900, leads: 0, verdict: "negative" },
  { query: "сервисный центр apple рядом", clicks: 155, spend: 9_400, leads: 11, verdict: "review" },
];

const verdictLabel = {
  keep: { label: "Оставить", tone: "success" },
  negative: { label: "В минус-фразы", tone: "critical" },
  review: { label: "Проверить", tone: "warning" },
} as const;

const queryColumns: DataTableColumn<QueryRow>[] = [
  { key: "query", header: "Запрос", render: (row) => row.query },
  { key: "clicks", header: "Клики", numeric: true, render: (row) => formatNumber(row.clicks) },
  { key: "spend", header: "Расход", numeric: true, render: (row) => formatCurrency(row.spend) },
  { key: "leads", header: "Лиды", numeric: true, render: (row) => formatNumber(row.leads) },
  {
    key: "verdict",
    header: "Решение",
    render: (row) => (
      <StatusBadge tone={verdictLabel[row.verdict].tone}>
        {verdictLabel[row.verdict].label}
      </StatusBadge>
    ),
  },
];

function QueryTable(props: Partial<DataTableProps<QueryRow>>) {
  return (
    <DataTable
      caption="Поисковые запросы за последние 7 дней"
      columns={queryColumns}
      rows={rows}
      rowKey={(row) => row.query}
      {...props}
    />
  );
}

export const Table: Story = { render: () => <QueryTable /> };

export const TableLoading: Story = { render: () => <QueryTable loading /> };

export const TableEmpty: Story = {
  render: () => (
    <QueryTable
      rows={[]}
      empty={{
        title: "Поисковых запросов пока нет",
        description: "Данные появятся после первых показов кампании.",
      }}
    />
  ),
};

export const TableError: Story = {
  render: () => (
    <QueryTable
      error={{
        title: "Не удалось загрузить запросы",
        requestId: "req_01JC8XN4K2QW",
        onRetry: () => undefined,
      }}
    />
  ),
};

export const Filters: Story = {
  render: function Render() {
    const [value, setValue] = useState("all");
    return (
      <FilterBar
        label="Фильтр проектов"
        value={value}
        onChange={setValue}
        options={[
          { value: "all", label: "Все", count: 8 },
          { value: "active", label: "Активные", count: 5 },
          { value: "archived", label: "Архив", count: 3 },
        ]}
      />
    );
  },
};

export const Projects: Story = {
  render: () => (
    <div className="grid grid-cols-2 gap-4">
      <ProjectCard
        name="Apple Service Тверь"
        status="active"
        spend={142_750}
        leads={267}
        cpl={535}
        trend={[88, 96, 91, 104, 118, 142]}
        onClick={() => undefined}
      />
      <ProjectCard
        name="Ремонт iPhone Москва"
        status="active"
        spend={98_320}
        leads={163}
        cpl={602}
        trend={[62, 71, 68, 78, 88, 98]}
        onClick={() => undefined}
      />
      <ProjectCard
        name="Запчасти iPhone СПб"
        status="paused"
        spend={56_410}
        leads={74}
        cpl={762}
        trend={[48, 52, 55, 54, 56, 56]}
        onClick={() => undefined}
      />
      <ProjectCard
        name="Trade-in iPhone"
        status="draft"
        spend={0}
        leads={0}
        cpl={0}
        onClick={() => undefined}
      />
    </div>
  ),
};

export const Integrations: Story = {
  render: () => (
    <div className="grid w-96 grid-cols-3 gap-2">
      <IntegrationCard name="Яндекс Директ" status="connected" icon={<IconTarget size={22} />} />
      <IntegrationCard name="Яндекс Метрика" status="degraded" icon={<IconChart size={22} />} />
      <IntegrationCard name="AmoCRM" status="error" icon={<IconUsers size={22} />} />
    </div>
  ),
};

export const Switcher: Story = {
  render: function Render() {
    const [selected, setSelected] = useState("p1");
    return (
      <div className="w-72">
        <ProjectSwitcher
          selectedId={selected}
          onSelect={setSelected}
          projects={[
            { id: "p1", name: "Apple Service Тверь", status: "active" },
            { id: "p2", name: "Ремонт iPhone Москва", status: "active" },
            { id: "p3", name: "Запчасти iPhone СПб", status: "paused" },
          ]}
        />
      </div>
    );
  },
};

/** Две оси: рубли и штуки на одной шкале несопоставимы. */
export const Chart: Story = {
  render: () => (
    <Card>
      <LineChart
        caption="Расходы в рублях (левая ось), лиды в штуках (правая ось) по дням"
        labels={["01.05", "02.05", "03.05", "04.05", "05.05", "06.05", "07.05"]}
        series={[
          {
            key: "spend",
            label: "Расходы, ₽",
            color: "var(--color-chart-1)",
            axis: "left",
            values: [88_400, 96_100, 91_300, 104_800, 99_200, 118_600, 142_750],
            format: formatCurrency,
          },
          {
            key: "leads",
            label: "Лиды, шт",
            color: "var(--color-chart-2)",
            axis: "right",
            values: [180, 195, 188, 214, 221, 238, 267],
            format: formatNumber,
          },
        ]}
      />
    </Card>
  ),
};

export const Assistant: Story = {
  render: () => (
    <Card className="w-[520px]">
      <div className="flex flex-col gap-4">
        <div className="flex items-center gap-3">
          <AiAvatar size={52} thinking />
          <p className="text-caption text-text-secondary">Анализирую данные проекта…</p>
        </div>
        <ChatComposer
          onSubmit={() => undefined}
          projectContext="Apple Service Тверь"
          suggestions={["Почему вырос CPL?", "Что сегодня требует внимания?"]}
        />
      </div>
    </Card>
  ),
};
