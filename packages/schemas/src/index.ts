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
export type ProjectUpdate = Schemas["ProjectUpdate"];
export type ProgressRead = Schemas["ProgressRead"];
export type OverviewRead = Schemas["OverviewRead"];
export type ProjectSummaryRead = Schemas["ProjectSummaryRead"];
export type StepRead = Schemas["StepRead"];
export type StepKey = Schemas["StepKey"];
export type StepState = Schemas["StepState"];
export type ProjectStatus = Schemas["ProjectStatus"];
export type EconomicsRead = Schemas["EconomicsRead"];
export type EconomicsUpdate = Schemas["EconomicsUpdate"];
export type EconomicsResponse = Schemas["EconomicsResponse"];
export type EconomicsSummaryRead = Schemas["EconomicsSummaryRead"];
export type MetricRead = Schemas["MetricRead"];
export type HealthResponse = Schemas["HealthResponse"];
export type OrganizationRead = Schemas["OrganizationRead"];
export type CurrentUserRead = Schemas["CurrentUserRead"];
export type MemberCreate = Schemas["MemberCreate"];
export type MemberUpdate = Schemas["MemberUpdate"];
export type MemberRead = Schemas["MemberRead"];
export type SessionRead = Schemas["SessionRead"];
export type SessionList = Schemas["SessionList"];
export type PlanRead = Schemas["PlanRead"];
export type UsageRead = Schemas["UsageRead"];
export type AuditRead = Schemas["AuditRead"];
export type AuditHistory = Schemas["AuditHistory"];
export type AuditHistoryItem = Schemas["AuditHistoryItem"];
export type CompetitorRead = Schemas["CompetitorRead"];
export type CompetitorList = Schemas["CompetitorList"];
export type CompetitorCreate = Schemas["CompetitorCreate"];
export type ComparisonRead = Schemas["ComparisonRead"];
export type FeatureRowRead = Schemas["FeatureRowRead"];
export type LaunchPlanRead = Schemas["LaunchPlanRead"];
export type BidStrategy = Schemas["BidStrategy"];
export type PlanStatus = Schemas["PlanStatus"];
export type KeywordRead = Schemas["KeywordRead"];
export type KeywordList = Schemas["KeywordList"];
export type ImportSummary = Schemas["ImportSummary"];
export type ClusterRead = Schemas["ClusterRead"];
export type ClusterList = Schemas["ClusterList"];
export type MinusWordRead = Schemas["MinusWordRead"];
export type MinusWordList = Schemas["MinusWordList"];
export type AdDraftRead = Schemas["AdDraftRead"];
export type AdDraftList = Schemas["AdDraftList"];
export type AdViolationRead = Schemas["AdViolationRead"];
export type MinusWordSetRead = Schemas["MinusWordSetRead"];
export type MinusWordSetList = Schemas["MinusWordSetList"];
export type NicheRead = Schemas["NicheRead"];
export type NicheList = Schemas["NicheList"];
export type NicheRequirementRead = Schemas["NicheRequirementRead"];
export type ApplySetResult = Schemas["ApplySetResult"];
export type SearchResult = Schemas["SearchResult"];
export type SearchProjectRead = Schemas["SearchProjectRead"];
export type SearchKeywordRead = Schemas["SearchKeywordRead"];
export type Intent = Schemas["Intent"];
export type NotificationRead = Schemas["NotificationRead"];
export type NotificationList = Schemas["NotificationList"];
export type ActivityRead = Schemas["ActivityRead"];
export type ActivityList = Schemas["ActivityList"];
export type ActivityAction = Schemas["ActivityAction"];
export type CategoryRead = Schemas["CategoryRead"];
export type AuditIssueRead = Schemas["AuditIssueRead"];
export type AuditChangesRead = Schemas["AuditChangesRead"];
export type AuditPageRead = Schemas["AuditPageRead"];
export type AuditPageList = Schemas["AuditPageList"];
export type DismissalCreate = Schemas["DismissalCreate"];
export type DismissalRead = Schemas["DismissalRead"];
export type DismissalList = Schemas["DismissalList"];
export type ModuleStatus = Schemas["ModuleStatus"];
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
      // Сессия живёт в куке, недоступной скриптам. Без credentials браузер её
      // не отправит, и любой запрос вернёт «требуется вход».
      credentials: "include",
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

  /**
   * Запрос к эндпоинту, который отвечает без тела (204).
   *
   * Обычный request тут не подходит: он всегда разбирает JSON и падает на
   * пустом ответе.
   */
  async requestNoContent(path: string, init: RequestInit = {}): Promise<void> {
    const response = await this.fetchImpl(`${this.baseUrl}${path}`, {
      ...init,
      credentials: "include",
      headers: { ...this.headers, ...init.headers },
    });

    if (!response.ok) {
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

  getProject(projectId: string): Promise<ProjectRead> {
    return this.request<ProjectRead>(`/api/v1/projects/${projectId}`);
  }

  updateProject(projectId: string, payload: ProjectUpdate): Promise<ProjectRead> {
    return this.request<ProjectRead>(`/api/v1/projects/${projectId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
  }

  /**
   * Кто вошёл. `null` означает «не вошёл» — это обычное состояние, а не сбой,
   * поэтому оно не превращается в ошибку.
   */
  async getCurrentUser(): Promise<CurrentUserRead | null> {
    try {
      return await this.request<CurrentUserRead>("/api/v1/auth/me");
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) return null;
      throw err;
    }
  }

  async logout(): Promise<void> {
    await this.requestNoContent("/api/v1/auth/logout", { method: "POST" });
  }

  /** Мои активные входы. Список личный: чужие сюда не попадают. */
  listSessions(): Promise<SessionList> {
    return this.request<SessionList>("/api/v1/auth/sessions");
  }

  async revokeSession(sessionId: string): Promise<void> {
    await this.requestNoContent(`/api/v1/auth/sessions/${sessionId}`, { method: "DELETE" });
  }

  addMember(payload: MemberCreate): Promise<MemberRead> {
    return this.request<MemberRead>("/api/v1/organization/members", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  updateMember(memberId: string, payload: MemberUpdate): Promise<MemberRead> {
    return this.request<MemberRead>(`/api/v1/organization/members/${memberId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
  }

  /** Своя организация: состав, лимиты и режим работы стенда. */
  getOrganization(): Promise<OrganizationRead> {
    return this.request<OrganizationRead>("/api/v1/organization");
  }

  /** Мягкое удаление проекта (v0.3 §61). */
  async deleteProject(projectId: string): Promise<void> {
    await this.requestNoContent(`/api/v1/projects/${projectId}`, { method: "DELETE" });
  }

  /** Сводка по всем проектам для главного экрана. */
  getOverview(): Promise<OverviewRead> {
    return this.request<OverviewRead>("/api/v1/overview");
  }

  /** Где находится проект по каноническому циклу и что делать дальше (v0.4 §3). */
  getProgress(projectId: string): Promise<ProgressRead> {
    return this.request<ProgressRead>(`/api/v1/projects/${projectId}/progress`);
  }

  /** План запуска. Считается на лету из экономики и аудита, не хранится. */
  getStrategy(projectId: string): Promise<LaunchPlanRead> {
    return this.request<LaunchPlanRead>(`/api/v1/projects/${projectId}/strategy`);
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

  /**
   * Журнал действий. Без `projectId` — по всей организации.
   */
  /** Что система заметила сама. Уведомления общие для организации. */
  listNotifications(unreadOnly = false): Promise<NotificationList> {
    const suffix = unreadOnly ? "?unread_only=true" : "";
    return this.request<NotificationList>(`/api/v1/notifications${suffix}`);
  }

  markNotificationRead(notificationId: string): Promise<NotificationRead> {
    return this.request<NotificationRead>(`/api/v1/notifications/${notificationId}/read`, {
      method: "POST",
    });
  }

  async markAllNotificationsRead(): Promise<void> {
    await this.requestNoContent("/api/v1/notifications/read-all", { method: "POST" });
  }

  listActivity(projectId?: string | null, limit?: number): Promise<ActivityList> {
    const query = new URLSearchParams();
    if (projectId) query.set("project_id", projectId);
    if (limit) query.set("limit", String(limit));
    const suffix = query.size > 0 ? `?${query.toString()}` : "";
    return this.request<ActivityList>(`/api/v1/activity${suffix}`);
  }

  importKeywords(projectId: string, text: string): Promise<ImportSummary> {
    return this.request<ImportSummary>(`/api/v1/projects/${projectId}/keywords/import`, {
      method: "POST",
      body: JSON.stringify({ text }),
    });
  }

  listKeywords(projectId: string, intent?: Intent | null): Promise<KeywordList> {
    const suffix = intent ? `?intent=${intent}` : "";
    return this.request<KeywordList>(`/api/v1/projects/${projectId}/keywords${suffix}`);
  }

  updateKeyword(projectId: string, keywordId: string, intent: Intent): Promise<KeywordRead> {
    return this.request<KeywordRead>(`/api/v1/projects/${projectId}/keywords/${keywordId}`, {
      method: "PATCH",
      body: JSON.stringify({ intent }),
    });
  }

  listClusters(projectId: string): Promise<ClusterList> {
    return this.request<ClusterList>(`/api/v1/projects/${projectId}/keywords/clusters`);
  }

  /** Справочник ниш. Одинаков для всех и меняется вместе с кодом, а не с данными. */
  listNiches(): Promise<NicheList> {
    return this.request<NicheList>(`/api/v1/niches`);
  }

  listMinusWords(projectId: string): Promise<MinusWordList> {
    return this.request<MinusWordList>(`/api/v1/projects/${projectId}/minus-words`);
  }

  addMinusWord(projectId: string, word: string): Promise<MinusWordRead> {
    return this.request<MinusWordRead>(`/api/v1/projects/${projectId}/minus-words`, {
      method: "POST",
      body: JSON.stringify({ word }),
    });
  }

  async deleteMinusWord(projectId: string, minusWordId: string): Promise<void> {
    await this.requestNoContent(`/api/v1/projects/${projectId}/minus-words/${minusWordId}`, {
      method: "DELETE",
    });
  }

  /**
   * Адрес выгрузки кампании файлом.
   *
   * Возвращается ссылка, а не содержимое: файл скачивает браузер, и делать это
   * через fetch значило бы держать весь CSV в памяти вкладки ради того же
   * результата.
   */
  campaignExportUrl(projectId: string): string {
    return `${this.baseUrl}/api/v1/projects/${projectId}/campaign/export.csv`;
  }

  /** Черновики объявлений по группам фраз. Ничего не сохраняется. */
  listAdDrafts(projectId: string): Promise<AdDraftList> {
    return this.request<AdDraftList>(`/api/v1/projects/${projectId}/ads`);
  }

  /** Наборы минус-слов организации: заготовки для новых проектов. */
  /** Поиск по проектам и фразам. */
  search(query: string): Promise<SearchResult> {
    return this.request<SearchResult>(`/api/v1/search?q=${encodeURIComponent(query)}`);
  }

  listMinusWordSets(): Promise<MinusWordSetList> {
    return this.request<MinusWordSetList>("/api/v1/minus-word-sets");
  }

  saveMinusWordSet(name: string, sourceProjectId: string): Promise<MinusWordSetRead> {
    return this.request<MinusWordSetRead>("/api/v1/minus-word-sets", {
      method: "POST",
      body: JSON.stringify({ name, source_project_id: sourceProjectId, words: [] }),
    });
  }

  applyMinusWordSet(projectId: string, setId: string): Promise<ApplySetResult> {
    return this.request<ApplySetResult>(
      `/api/v1/projects/${projectId}/minus-words/apply/${setId}`,
      { method: "POST" },
    );
  }

  listCompetitors(projectId: string): Promise<CompetitorList> {
    return this.request<CompetitorList>(`/api/v1/projects/${projectId}/competitors`);
  }

  addCompetitor(projectId: string, payload: CompetitorCreate): Promise<CompetitorRead> {
    return this.request<CompetitorRead>(`/api/v1/projects/${projectId}/competitors`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  recheckCompetitor(projectId: string, competitorId: string): Promise<CompetitorRead> {
    return this.request<CompetitorRead>(
      `/api/v1/projects/${projectId}/competitors/${competitorId}/recheck`,
      { method: "POST" },
    );
  }

  async deleteCompetitor(projectId: string, competitorId: string): Promise<void> {
    await this.requestNoContent(`/api/v1/projects/${projectId}/competitors/${competitorId}`, {
      method: "DELETE",
    });
  }

  /** Сравнение своего сайта с конкурентами (v0.3 §16). */
  getComparison(projectId: string): Promise<ComparisonRead> {
    return this.request<ComparisonRead>(`/api/v1/projects/${projectId}/comparison`);
  }

  /**
   * Последний аудит сайта. `null` означает, что аудит ещё ни разу не запускали —
   * это не ошибка и не пустой результат.
   */
  getAudit(projectId: string, url?: string | null): Promise<AuditRead | null> {
    const suffix = url ? `?url=${encodeURIComponent(url)}` : "";
    return this.request<AuditRead | null>(`/api/v1/projects/${projectId}/audit${suffix}`);
  }

  /** Проверенные страницы проекта. Список выводится из проверок. */
  listAuditPages(projectId: string): Promise<AuditPageList> {
    return this.request<AuditPageList>(`/api/v1/projects/${projectId}/audit/pages`);
  }

  /** История проверок: помогли доработки сайта или нет (v0.3 §62). */
  getAuditHistory(projectId: string): Promise<AuditHistory> {
    return this.request<AuditHistory>(`/api/v1/projects/${projectId}/audits`);
  }

  /**
   * Запускает аудит. Ответ приходит сразу со статусом «в очереди»: работа идёт в
   * фоне, потому что обход чужого сайта занимает десятки секунд (v0.3 §6).
   */
  /** Отметить замечание неактуальным для проекта. Балл при этом не меняется. */
  dismissIssue(projectId: string, payload: DismissalCreate): Promise<DismissalRead> {
    return this.request<DismissalRead>(`/api/v1/projects/${projectId}/audit/dismissals`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  async restoreIssue(projectId: string, issueKey: string): Promise<void> {
    await this.requestNoContent(`/api/v1/projects/${projectId}/audit/dismissals/${issueKey}`, {
      method: "DELETE",
    });
  }

  /** Без адреса проверяется главная страница проекта. */
  startAudit(projectId: string, url?: string | null): Promise<AuditRead> {
    return this.request<AuditRead>(`/api/v1/projects/${projectId}/audit`, {
      method: "POST",
      body: JSON.stringify({ url: url ?? null }),
    });
  }
}
