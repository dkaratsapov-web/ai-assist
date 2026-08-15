import next from "eslint-config-next";

/**
 * eslint-config-next 16 поставляется уже в формате flat config, поэтому слой
 * совместимости FlatCompat не нужен — с ним конфигурация ломается на
 * циклической ссылке внутри плагина react.
 */
const config = [
  ...next,
  {
    ignores: [".next/**", "node_modules/**", "storybook-static/**"],
  },
];

export default config;
