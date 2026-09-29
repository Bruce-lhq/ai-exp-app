export async function api<T = any>(
  path: string,
  body?: unknown,
  method?: string,
  options: { background?: boolean; signal?: AbortSignal } = {},
): Promise<T> {
  const requestMethod = method || (body === undefined ? "GET" : "POST");
  const payload = body === undefined && requestMethod !== "GET" ? {} : body;
  const local = path.startsWith("/api/analysis/") && !(body as any)?.live_ids?.length ||
    path.startsWith("/api/templates") || path.startsWith("/api/notifications") ||
    path === "/api/connection" ||
    (path.startsWith("/api/history") && requestMethod === "GET");
  const loading = (delta: number) => {
    if (!local && !options.background && typeof window !== "undefined")
      window.dispatchEvent(new CustomEvent("ai-exp-loading", { detail: delta }));
  };
  loading(1);
  let response: Response;
  try {
    response = await fetch(path, {
      method: requestMethod,
      credentials: "same-origin",
      signal: options.signal,
      headers:
        payload === undefined ? undefined : { "Content-Type": "application/json" },
      body: payload === undefined ? undefined : JSON.stringify(payload),
    });
  } finally {
    loading(-1);
  }
  if (!response.ok) {
    let message;
    try {
      const error = await response.json();
      message =
        typeof error.detail === "string"
          ? error.detail
          : JSON.stringify(error.detail || error.error || error);
    } catch {
      message = response.statusText;
    }
    throw new Error(message || `请求失败 (${response.status})`);
  }
  if (response.status === 204) return undefined as T;
  return response.json();
}
export function download(
  content: string,
  name: string,
  type = "text/plain;charset=utf-8",
) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export function items<T = any>(data: any, key = "items"): T[] {
  return Array.isArray(data) ? data : data?.[key] || [];
}
export type Project = { id: string; name: string; host: string; path: string };
export type Parameters = {
  training: Record<string, any>;
  runtime: { gpu_count: number };
};
export type Field = {
  key: string;
  kind: string;
  default: any;
  has_default: boolean;
  required?: boolean;
  nullable?: boolean;
  choices?: any[];
  help?: string;
  group?: string;
  constraints?: { min?: number; max?: number };
};
export type Run = {
  id: string;
  run_id?: string;
  display_name: string;
  status: string;
  parameters?: Parameters;
  gpu_ids?: number[];
  project_id?: string;
  sync_status?: string;
  archived?: boolean;
  tags?: string[];
  notes?: string;
  progress?: string;
  remaining?: string;
  queue_name?: string;
  external?: boolean;
};
