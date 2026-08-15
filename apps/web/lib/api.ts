import { ApiClient } from "@ads-os/schemas";

/**
 * Клиент API.
 *
 * Контекст пользователя приходит из сессии в куке — её ставит сервер после
 * входа через Яндекс ID, и скриптам она недоступна. Заголовки с организацией
 * больше не передаются: заголовку как основанию для авторизации доверять
 * нельзя (v0.3 §93), и на сервере этот путь остался только для локальной
 * разработки.
 */
export function createApiClient(): ApiClient {
  return new ApiClient({ baseUrl: process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000" });
}
