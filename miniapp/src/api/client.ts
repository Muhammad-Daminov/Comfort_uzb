/**
 * Fetch wrapper — the only place that talks to the backend. Every screen
 * goes through this, never `fetch` directly, so the auth header, error
 * mapping, and JSON handling stay in one place (docs/04_API_SPEC.md's
 * error envelope: {"error": {"code", "message", "details"}}).
 */
import { getToken } from "../state/session";

export type ApiErrorKind =
  | "unauthorized" // 401
  | "forbidden" // 403
  | "not_found" // 404
  | "conflict" // 409
  | "validation" // 422
  | "server_error" // 5xx
  | "network"; // fetch itself threw (offline, timeout, DNS, ...)

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status: number | null;
  readonly code: string | null;
  readonly details: unknown;

  constructor(kind: ApiErrorKind, message: string, status: number | null, code: string | null, details: unknown) {
    super(message);
    this.kind = kind;
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

function kindForStatus(status: number): ApiErrorKind {
  if (status === 401) return "unauthorized";
  if (status === 403) return "forbidden";
  if (status === 404) return "not_found";
  if (status === 409) return "conflict";
  if (status === 422) return "validation";
  return "server_error";
}

const API_BASE = import.meta.env.VITE_API_BASE ?? "";

interface ErrorEnvelope {
  code?: string;
  message?: string;
  details?: unknown;
}

/**
 * The backend's §13.5 envelope is `{"error": {code, message, details}}`.
 * Before the audit the API only ever sent FastAPI's `{"detail": ...}` — a
 * plain string, or the envelope nested under `detail` — so `ApiError.code`
 * was always null and the checkout's PRICE_MISMATCH handling never ran.
 * Accept every shape, in order of preference, so a future backend that
 * drops `detail` and an old one that only has it both keep working.
 */
export function extractErrorEnvelope(payload: unknown): ErrorEnvelope | null {
  if (!payload || typeof payload !== "object") return null;
  const body = payload as { error?: unknown; detail?: unknown };
  if (body.error && typeof body.error === "object") return body.error as ErrorEnvelope;
  const detail = body.detail;
  if (detail && typeof detail === "object") {
    const nested = (detail as { error?: unknown }).error;
    if (nested && typeof nested === "object") return nested as ErrorEnvelope;
  }
  if (typeof detail === "string") return { message: detail };
  return null;
}

export interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  body?: unknown;
  idempotencyKey?: string;
  isFormData?: boolean;
  signal?: AbortSignal;
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (options.idempotencyKey) headers["Idempotency-Key"] = options.idempotencyKey;

  let body: BodyInit | undefined;
  if (options.body !== undefined) {
    if (options.isFormData) {
      body = options.body as FormData;
    } else {
      headers["Content-Type"] = "application/json";
      body = JSON.stringify(options.body);
    }
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method: options.method ?? "GET",
      headers,
      body,
      signal: options.signal,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err; // let callers distinguish a deliberate cancel from a real failure
    throw new ApiError("network", "Internet aloqasi yo'q. Qaytadan urinib ko'ring.", null, null, null);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  let payload: unknown = null;
  const text = await response.text();
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = null;
    }
  }

  if (!response.ok) {
    const errorBody = extractErrorEnvelope(payload);
    throw new ApiError(
      kindForStatus(response.status),
      errorBody?.message || `So'rov bajarilmadi (${response.status})`,
      response.status,
      errorBody?.code ?? null,
      errorBody?.details ?? null,
    );
  }

  return payload as T;
}
