import { API } from "../api";
import type {
  CommitStrategyRunImportInput,
  PreviewStrategyRunImportInput,
  StrategyCreateInput,
  StrategyDefinition,
  StrategyDetail,
  StrategyRunDetail,
  StrategyRunImportPreview,
  StrategyRunImportResult,
  StrategyRunList,
  StrategyRunListFilters,
  StrategyRunMetrics,
  StrategyRunTradeFilters,
  StrategyRunTradeList,
  StrategyVersionCreateInput,
  StrategyVersionDetail,
} from "./types";

export interface FastApiValidationIssue {
  type?: string;
  loc?: Array<string | number>;
  msg?: string;
}

function validationIssueText(issue: FastApiValidationIssue): string {
  const location = (issue.loc ?? [])
    .filter((part) => part !== "body")
    .map(String)
    .join(".");
  const message = issue.msg?.trim() || issue.type?.trim() || "Invalid value";
  return location ? `${location}: ${message}` : message;
}

function detailText(detail: unknown, statusText: string): string {
  if (typeof detail === "string" && detail.trim()) return detail.trim();

  if (Array.isArray(detail)) {
    const messages = detail
      .filter((item): item is FastApiValidationIssue => Boolean(item) && typeof item === "object")
      .map(validationIssueText)
      .filter(Boolean);
    if (messages.length) return messages.join("; ");
  }

  if (detail && typeof detail === "object") {
    try {
      return JSON.stringify(detail).slice(0, 1_000);
    } catch {
      // Fall through to the HTTP status text.
    }
  }

  return statusText || "Request failed";
}

export class StrategyLabApiError extends Error {
  readonly status: number;
  readonly path: string;
  readonly detail: unknown;

  constructor({
    status,
    statusText,
    path,
    detail,
  }: {
    status: number;
    statusText: string;
    path: string;
    detail: unknown;
  }) {
    const message = detailText(detail, statusText);
    super(`Strategy Lab API ${path} -> ${status}: ${message}`);
    this.name = "StrategyLabApiError";
    this.status = status;
    this.path = path;
    this.detail = detail;
  }
}

async function responseBody(response: Response): Promise<unknown> {
  if (response.status === 204) return undefined;

  const text = await response.text();
  if (!text.trim()) return undefined;

  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, {
    cache: "no-store",
    ...init,
  });
  const body = await responseBody(response);

  if (!response.ok) {
    const detail =
      body && typeof body === "object" && "detail" in body
        ? (body as { detail: unknown }).detail
        : body;
    throw new StrategyLabApiError({
      status: response.status,
      statusText: response.statusText,
      path,
      detail,
    });
  }

  return body as T;
}

function jsonRequest<T>(path: string, method: "POST" | "PATCH", body: unknown): Promise<T> {
  return request<T>(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

function queryPath(path: string, values: Record<string, string | number | undefined>): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (value !== undefined) query.set(key, String(value));
  }
  const encoded = query.toString();
  return encoded ? `${path}?${encoded}` : path;
}

export function listStrategies(): Promise<StrategyDefinition[]> {
  return request<StrategyDefinition[]>("/strategy-lab/strategies");
}

export function createStrategy(input: StrategyCreateInput): Promise<StrategyDefinition> {
  return jsonRequest<StrategyDefinition>("/strategy-lab/strategies", "POST", input);
}

export function getStrategy(strategyId: string): Promise<StrategyDetail> {
  return request<StrategyDetail>(`/strategy-lab/strategies/${encodeURIComponent(strategyId)}`);
}

export function createVersion(
  strategyId: string,
  input: StrategyVersionCreateInput,
): Promise<StrategyVersionDetail> {
  return jsonRequest<StrategyVersionDetail>(
    `/strategy-lab/strategies/${encodeURIComponent(strategyId)}/versions`,
    "POST",
    input,
  );
}

export function getVersion(versionId: string): Promise<StrategyVersionDetail> {
  return request<StrategyVersionDetail>(
    `/strategy-lab/versions/${encodeURIComponent(versionId)}`,
  );
}

export function listRuns(filters: StrategyRunListFilters = {}): Promise<StrategyRunList> {
  return request<StrategyRunList>(
    queryPath("/strategy-lab/runs", {
      strategy_id: filters.strategyId,
      version_id: filters.versionId,
      limit: filters.limit,
      offset: filters.offset,
    }),
  );
}

export function getRun(runId: string): Promise<StrategyRunDetail> {
  return request<StrategyRunDetail>(`/strategy-lab/runs/${encodeURIComponent(runId)}`);
}

export function getRunTrades(
  runId: string,
  filters: StrategyRunTradeFilters = {},
): Promise<StrategyRunTradeList> {
  return request<StrategyRunTradeList>(
    queryPath(`/strategy-lab/runs/${encodeURIComponent(runId)}/trades`, {
      direction: filters.direction,
      outcome: filters.outcome,
      entry_date_from: filters.entryDateFrom,
      entry_date_to: filters.entryDateTo,
      limit: filters.limit,
      offset: filters.offset,
    }),
  );
}

export async function getMetricsOrNull(runId: string): Promise<StrategyRunMetrics | null> {
  try {
    return await request<StrategyRunMetrics>(
      `/strategy-lab/runs/${encodeURIComponent(runId)}/metrics`,
    );
  } catch (error) {
    if (error instanceof StrategyLabApiError && error.status === 404) return null;
    throw error;
  }
}

export function recalculateMetrics(runId: string): Promise<StrategyRunMetrics> {
  return request<StrategyRunMetrics>(
    `/strategy-lab/runs/${encodeURIComponent(runId)}/metrics/recalculate`,
    { method: "POST" },
  );
}

export function previewImport({
  strategyVersionId,
  sourceTimezone,
  file,
}: PreviewStrategyRunImportInput): Promise<StrategyRunImportPreview> {
  const body = new FormData();
  body.append("strategy_version_id", strategyVersionId);
  body.append("source_timezone", sourceTimezone);
  body.append("file", file, file.name);
  return request<StrategyRunImportPreview>("/strategy-lab/imports/preview", {
    method: "POST",
    body,
  });
}

export function commitImport({
  metadata,
  file,
}: CommitStrategyRunImportInput): Promise<StrategyRunImportResult> {
  const body = new FormData();
  body.append("metadata", JSON.stringify(metadata));
  body.append("file", file, file.name);
  return request<StrategyRunImportResult>("/strategy-lab/runs/import", {
    method: "POST",
    body,
  });
}

export const strategyLabApi = {
  listStrategies,
  createStrategy,
  getStrategy,
  createVersion,
  getVersion,
  listRuns,
  getRun,
  getRunTrades,
  getMetricsOrNull,
  recalculateMetrics,
  previewImport,
  commitImport,
};
