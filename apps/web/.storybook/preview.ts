import type { Preview } from "@storybook/nextjs-vite";
import "../app/globals.css";

const preview: Preview = {
  parameters: {
    layout: "centered",
    controls: { expanded: true },
    // Проверка доступности включена по умолчанию: правила из v0.3 §139
    // должны нарушаться заметно, а не тихо.
    a11y: { test: "todo" },
    backgrounds: {
      options: {
        surface: { name: "Поверхность", value: "#FFFFFF" },
        page: { name: "Фон страницы", value: "#F7F7F8" },
      },
    },
  },
  initialGlobals: {
    backgrounds: { value: "page" },
  },
};

export default preview;
