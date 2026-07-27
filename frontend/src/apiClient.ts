export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: string,
    public readonly requestId?: string,
  ) {
    super(detail);
    this.name = "ApiError";
  }
}

type RequestOptions = Omit<RequestInit, "body"> & {
  body?: unknown;
  authenticated?: boolean;
  csrfCookie?: "faq_csrf" | "faq_login_csrf";
};

function cookie(name: string) {
  return document.cookie.split("; ").find((item) => item.startsWith(`${name}=`))?.slice(name.length + 1) ?? "";
}

function loginUrl() {
  const current = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  return `/login?returnTo=${encodeURIComponent(current)}`;
}

async function parse(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) return undefined;
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("json")) {
    try { return JSON.parse(text); } catch { return text; }
  }
  return text;
}

export async function apiClient<Result = unknown>(url: string, options: RequestOptions = {}): Promise<Result> {
  const method = (options.method ?? "GET").toUpperCase();
  const mutating = !["GET", "HEAD", "OPTIONS"].includes(method);
  const headers = new Headers(options.headers);
  let body: BodyInit | undefined;
  if (options.body !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(options.body);
  }
  if (mutating) headers.set("X-CSRF-Token", cookie(options.csrfCookie ?? "faq_csrf"));
  const response = await fetch(url, { ...options, method, body, headers, credentials: "same-origin" });
  const payload = await parse(response);
  if (!response.ok) {
    const detail = typeof payload === "object" && payload && "detail" in payload
      ? String(payload.detail)
      : typeof payload === "string" && payload ? payload : `Request failed (${response.status})`;
    const requestId = response.headers.get("x-request-id") ??
      (typeof payload === "object" && payload && "request_id" in payload ? String(payload.request_id) : undefined);
    if (response.status === 401 && options.authenticated !== false && window.location.pathname !== "/login") {
      window.location.assign(loginUrl());
    }
    throw new ApiError(response.status, detail, requestId);
  }
  return payload as Result;
}

export function apiRequest<Result = unknown>(url: string, method = "GET", body?: unknown) {
  return apiClient<Result>(url, { method, body });
}
