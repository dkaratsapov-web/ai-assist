import { ApiClient } from "@ads-os/schemas";

/**
 * Клиент API.
 *
 * Контекст организации передаётся заголовками — временный режим, пока не
 * подключена настоящая аутентификация с MFA (v0.3 §91). Backend принимает такие
 * заголовки только вне production, поэтому режим невозможно случайно перенести
 * на боевой стенд.
 */
export function createApiClient(): ApiClient {
  const baseUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  const organizationId = process.env.NEXT_PUBLIC_DEMO_ORG_ID ?? "";
  const userId = process.env.NEXT_PUBLIC_DEMO_USER_ID ?? "";

  return new ApiClient({
    baseUrl,
    headers: {
      "X-Organization-Id": organizationId,
      "X-User-Id": userId,
      "X-User-Role": "specialist",
    },
  });
}

/** Настроен ли доступ к API. Без контекста запросы вернут 403. */
export function isApiConfigured(): boolean {
  return Boolean(process.env.NEXT_PUBLIC_DEMO_ORG_ID && process.env.NEXT_PUBLIC_DEMO_USER_ID);
}
