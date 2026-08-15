/**
 * Типы и клиент API ADS OS.
 *
 * Всё, что здесь есть, выведено из OpenAPI (v0.4 §18). Руками описывать формы
 * запросов и ответов запрещено: расхождение между Python и TypeScript ловится в
 * CI, но только если второй стороны просто не существует как отдельного
 * источника правды.
 */

import type { components, paths } from "./openapi.d.ts";

export type { components, paths };

type Schemas = components["schemas"];

export type ProjectRead = Schemas["ProjectRead"];
export type ProjectList = Schemas["ProjectList"];
export type ProjectCreate = Schemas["ProjectCreate"];
export type EconomicsRead = Schemas["EconomicsRead"];
export type EconomicsUpdate = Schemas["EconomicsUpdate"];
export type EconomicsResponse = Schemas["EconomicsResponse"];
export type EconomicsSummaryRead = Schemas["EconomicsSummaryRead"];
export type MetricRead = Schemas["MetricRead"];
export type HealthResponse = Schemas["HealthResponse"];
export type Availability = Schemas["Availability"];
export type EconomicsMode = Schemas["EconomicsMode"];
export type MainConversion = Schemas["MainConversion"];

/** Форма ошибки, единая для всех эндпоинтов. */
export interface ErrorBody {
  error_code: string;
  message: string;
  request_id: string;
  retryable: boolean;
  details?: Record<string, unknown> | null;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly body: ErrorBody,
  ) {
    super(body.message);
    this.name = "ApiError";
  }

  /** Показывается пользователю рядом с предложением обратиться в поддержку. */
  get requestId(): string {
    return this.body.request_id;
  }
}

export interface ApiClientOptions {
  baseUrl: string;
  /**
   * Заголовки контекста.
   *
   * Временный способ передать организацию и пользователя, пока не подключена
   * настоящая аутентификация с MFA (v0.3 §91). Заменяется на сессию целиком,
   * не затрагивая вызывающий код.
   */
  headers?: Record<string, string>;
  fetch?: typeof fetch;
}

export class ApiClient {
  private readonly baseUrl: string;
  private readonly headers: Record<string, string>;
  private readonly fetchImpl: typeof fetch;

  constructor(options: ApiClientOptions) {
    this.baseUrl = options.baseUrl.replace(/\/$/, "");
    this.headers = options.headers ?? {};
    // fetch обязателен к привязке: сохранённый в поле и вызванный как метод
    // объекта, он получает в this экземпляр клиента вместо window и падает с
    // «Illegal invocation».
    this.fetchImpl = options.fetch ?? globalThis.fetch.bind(globalThis);
  }

  async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const response = await this.fetchImpl(`${this.baseUrl}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...this.headers,
        ...init.headers,
      },
    });

    if (!response.ok) {
      // Ответ об ошибке имеет известную форму; если её нет — значит упал не
      // сервис, а что-то перед ним, и это тоже нужно показать честно.
      const body = (await response.json().catch(() => null)) as ErrorBody | null;
      throw new ApiError(
        response.status,
        body ?? {
          error_code: "unexpected_response",
          message: "Сервис недоступен",
          request_id: "-",
          retryable: true,
        },
      );
    }

    return (await response.json()) as T;
  }

  health(): Promise<HealthResponse> {
    return this.request<HealthResponse>("/api/v1/health");
  }

  listProjects(): Promise<ProjectList> {
    return this.request<ProjectList>("/api/v1/projects");
  }

  createProject(payload: ProjectCreate): Promise<ProjectRead> {
    return this.request<ProjectRead>("/api/v1/projects", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  getEconomics(projectId: string): Promise<EconomicsResponse> {
    return this.request<EconomicsResponse>(`/api/v1/projects/${projectId}/economics`);
  }

  updateEconomics(projectId: string, payload: EconomicsUpdate): Promise<EconomicsResponse> {
    return this.request<EconomicsResponse>(`/api/v1/projects/${projectId}/economics`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  }
}
