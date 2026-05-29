// Thin fetch wrapper. Token lives in localStorage; that's enough for a
// prototype and avoids a session-cookie / CSRF dance with the serverless
// backend. The Vite dev server proxies /api -> Django (see vite.config.ts).

const API_BASE =
  (import.meta as any).env?.VITE_API_URL?.replace(/\/$/, "") || "";

const TOKEN_KEY = "breathe_token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

async function request<T>(
  path: string,
  init: RequestInit = {},
  isForm = false
): Promise<T> {
  const headers: Record<string, string> = {
    ...(init.headers as Record<string, string> | undefined),
  };
  if (!isForm) headers["Content-Type"] = "application/json";
  const token = getToken();
  if (token) headers["Authorization"] = `Token ${token}`;

  const res = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || JSON.stringify(body);
    } catch {
      // swallow
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as unknown as T;
  return res.json();
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

// ---- Endpoints ----

export type Tenant = {
  id: string;
  name: string;
  slug: string;
  country_code: string;
  created_at: string;
};

export type Me = {
  id: number;
  username: string;
  email: string;
  role: "analyst" | "admin";
  tenant: Tenant | null;
};

export async function login(username: string, password: string) {
  const data = await request<{ token: string }>("/api/auth/token/", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
  setToken(data.token);
  return data.token;
}

export const whoami = () => request<Me>("/api/auth/whoami/");

export type ActivityRecord = {
  id: string;
  tenant: string;
  scope: 1 | 2 | 3;
  activity_type: string;
  description: string;
  quantity_raw: string;
  unit_raw: string;
  quantity_normalized: string;
  unit_normalized: string;
  period_start: string;
  period_end: string;
  co2e_kg: string | null;
  cost_amount: string | null;
  cost_currency: string;
  status: "pending" | "approved" | "rejected" | "flagged" | "locked";
  flags: string[];
  source_system: string;
  is_edited: boolean;
  factor_activity: string | null;
  factor_region: string | null;
  factor_year: number | null;
};

export type Paged<T> = {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
};

export const listRecords = (filters: Record<string, string> = {}) => {
  const qs = new URLSearchParams(filters).toString();
  return request<Paged<ActivityRecord>>(`/api/records/${qs ? `?${qs}` : ""}`);
};

export const getRecord = (id: string) => request<any>(`/api/records/${id}/`);

export const approveRecord = (id: string, note: string = "") =>
  request<any>(`/api/records/${id}/approve/`, {
    method: "POST",
    body: JSON.stringify({ note }),
  });

export const rejectRecord = (id: string, note: string = "") =>
  request<any>(`/api/records/${id}/reject/`, {
    method: "POST",
    body: JSON.stringify({ note }),
  });

export const editRecord = (id: string, body: any) =>
  request<any>(`/api/records/${id}/edit/`, {
    method: "POST",
    body: JSON.stringify(body),
  });

export const listBatches = () =>
  request<Paged<any>>("/api/batches/");

export const listPeriods = () =>
  request<Paged<any>>("/api/reporting-periods/");

export const lockPeriod = (id: string) =>
  request<any>(`/api/reporting-periods/${id}/lock/`, { method: "POST" });

export const unlockPeriod = (id: string) =>
  request<any>(`/api/reporting-periods/${id}/unlock/`, { method: "POST" });

export const getSummary = () => request<any>("/api/summary/");

export const listFactors = () =>
  request<Paged<any>>("/api/factors/");

export async function ingest(
  source: "sap" | "utility-csv" | "utility-pdf" | "travel",
  file: File
) {
  const fd = new FormData();
  fd.append("file", file);
  return request<any>(`/api/ingest/${source}/`, { method: "POST", body: fd }, true);
}
