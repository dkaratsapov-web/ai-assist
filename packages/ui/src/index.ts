/**
 * Библиотека компонентов AI Helper Pro.
 *
 * Состав соответствует v0.4 §22: переиспользуемые компоненты, а не страницы.
 * Копировать разметку одной и той же карточки по экранам запрещено (v0.3 §142).
 */

export { cn } from "./lib/cn";
export { toneClasses, type ToneClasses } from "./lib/tone";
export * from "./lib/format";

export { Spinner, type SpinnerProps } from "./components/Spinner";
export {
  Button,
  IconButton,
  type ButtonProps,
  type ButtonSize,
  type ButtonVariant,
  type IconButtonProps,
} from "./components/Button";
export { Input, SearchInput, type InputProps, type SearchInputProps } from "./components/Input";
export { Skeleton, SkeletonText, type SkeletonProps } from "./components/Skeleton";

export {
  StatusBadge,
  SeverityBadge,
  ProjectStatusBadge,
  ModuleStatusBadge,
  IntegrationStatusBadge,
  type StatusBadgeProps,
} from "./components/StatusBadge";
export { MetricTrend, type MetricPolarity, type MetricTrendProps } from "./components/MetricTrend";

export {
  Card,
  CardHeader,
  Section,
  type CardProps,
  type CardHeaderProps,
  type CardTone,
  type SectionProps,
} from "./components/Card";
export { Hint, Details, type HintProps, type DetailsProps } from "./components/Hint";
export { ListRow, type ListRowProps } from "./components/ListRow";
export { Sparkline, type SparklineProps } from "./components/Sparkline";
export { LineChart, type ChartSeries, type LineChartProps } from "./components/LineChart";
export { KpiCard, type KpiCardProps } from "./components/KpiCard";
export {
  StatStrip,
  ProgressBar,
  type Stat,
  type StatStripProps,
  type ProgressBarProps,
} from "./components/StatStrip";

export { RecommendationCard, type RecommendationCardProps } from "./components/RecommendationCard";
export { AlertCard, type AlertCardProps } from "./components/AlertCard";
export { ProjectCard, type ProjectCardProps } from "./components/ProjectCard";
export { IntegrationCard, type IntegrationCardProps } from "./components/IntegrationCard";
export {
  WorkflowStepper,
  type WorkflowStep,
  type WorkflowStepperProps,
} from "./components/WorkflowStepper";

export { DataTable, type DataTableColumn, type DataTableProps } from "./components/DataTable";
export { FilterBar, type FilterBarProps, type FilterOption } from "./components/FilterBar";

export { Modal, type ModalProps } from "./components/Modal";
export { Drawer, type DrawerProps } from "./components/Drawer";
export {
  ConfirmationDialog,
  type ChangePreview,
  type ConfirmationDialogProps,
} from "./components/ConfirmationDialog";

export { EmptyState, type EmptyStateProps } from "./components/EmptyState";
export { ErrorState, type ErrorStateProps } from "./components/ErrorState";

export { ChatComposer, type ChatComposerProps } from "./components/ChatComposer";
export {
  ProjectSwitcher,
  type ProjectSwitcherProps,
  type SwitchableProject,
} from "./components/ProjectSwitcher";
export { AiAvatar, type AiAvatarProps } from "./components/AiAvatar";
