import type { StorybookConfig } from "@storybook/nextjs-vite";

/**
 * Изолированный превью компонентов (v0.4 §22).
 *
 * Истории пишутся только для переиспользуемой библиотеки, не для страниц:
 * страницы проверяются на demo-проекте в самом приложении.
 */
const config: StorybookConfig = {
  stories: ["../../../packages/ui/src/**/*.stories.@(ts|tsx)"],
  addons: ["@storybook/addon-a11y"],
  framework: {
    name: "@storybook/nextjs-vite",
    options: {},
  },
};

export default config;
