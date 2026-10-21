import type { ApiErrorBody } from "./types";
import { mockFetch } from "../mock/server";

function detectMock(): boolean {
  if (import.meta.env.VITE_MOCK === "1") return true;
  try {
    const p = new URLSearchParams(window.location.search);
    if (p.get("mock") === "1") {
      sessionStorage.setItem("ts.mock", "1");
      return true;
    }
    if (p.get("mock") === "0") {
      sessionStorage.removeItem("ts.mock");
      return false;
    }
    return sessionStorage.getItem("ts.mock") === "1";
  } catch {
    return false;
  }
}

export const MOCK = detectMock();

export class ApiError extends Error {
  status: number;
  hint?: string;
  constructor(status: number, body: ApiErrorBody) {
    super(body.detail || `Request failed (${status})`);
    this.status = status;
    this.hint = body.hint;
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  if (MOCK) {
    const r = await mockFetch(method, path, body);
    if (r.status >= 400) throw new ApiError(r.status, r.body as ApiErrorBody);
    return r.body as T;
  }
  let res: Response;
  try {
    res = await fetch(path, {
      method,
      headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError(0, {
      detail: "Can't reach the station service.",
      hint: "Check that station serve is running on this PC.",
    });
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  let data: unknown = undefined;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = { detail: text };
    }
  }
  if (!res.ok) {
    const looksProxied = res.status >= 500 && (!text || !text.trim().startsWith("{"));
    if (looksProxied)
      throw new ApiError(res.status, {
        detail: "The station service isn't responding.",
        hint: "Check that station serve is running on the station PC.",
      });
    const b = (data ?? {}) as Partial<ApiErrorBody> & { detail?: unknown };
    const detail =
      typeof b.detail === "string"
        ? b.detail
        : Array.isArray(b.detail)
          ? "The request was rejected: " + JSON.stringify(b.detail)
          : `Request failed (${res.status})`;
    throw new ApiError(res.status, { detail, hint: b.hint });
  }
  return data as T;
}

async function requestText(path: string): Promise<string> {
  if (MOCK) {
    const r = await mockFetch("GET", path);
    if (r.status >= 400) throw new ApiError(r.status, r.body as ApiErrorBody);
    return typeof r.body === "string" ? r.body : JSON.stringify(r.body, null, 2);
  }
  const res = await fetch(path);
  const text = await res.text();
  if (!res.ok) {
    let body: ApiErrorBody = { detail: `Request failed (${res.status})` };
    try {
      body = JSON.parse(text) as ApiErrorBody;
    } catch {
      /* plain text error */
    }
    throw new ApiError(res.status, body);
  }
  // A JSON-encoded string is unwrapped; anything else is returned as-is.
  try {
    const v = JSON.parse(text);
    if (typeof v === "string") return v;
  } catch {
    /* not JSON */
  }
  return text;
}

export const api = {
  text: requestText,
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body ?? {}),
  put: <T>(path: string, body: unknown) => request<T>("PUT", path, body),
  patch: <T>(path: string, body: unknown) => request<T>("PATCH", path, body),
  del: <T>(path: string) => request<T>("DELETE", path),
};

export function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === null || v === undefined || v === "") continue;
    p.set(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}

export function wsUrl(path: string): string {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}${path}`;
}
