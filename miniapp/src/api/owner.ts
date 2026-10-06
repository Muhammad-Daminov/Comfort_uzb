import { apiRequest } from "./client";

export interface DashboardSummary {
  order_counts_by_status: Record<string, number>;
  total_revenue: number;
  product_count: number;
  active_product_count: number;
  low_stock_threshold: number;
  low_stock_variants: Array<{ variant_id: number; sku: string; product_name: string; available: number }>;
  recent_orders: Array<{ id: number; order_number: string; status: string; total_amount: number; created_at: string }>;
  recent_payments: Array<{ id: number; order_id: number; amount: number; status: string; submitted_at: string }>;
}

export function getDashboard(): Promise<DashboardSummary> {
  return apiRequest<DashboardSummary>("/owner/dashboard");
}

export interface FinanceSummary {
  revenue: number;
  order_count: number;
  payment_status_breakdown: Array<{ status: string; count: number; total_amount: number }>;
  payments: Array<{
    payment_id: number;
    order_id: number;
    amount: number;
    status: string;
    submitted_at: string;
    hidden_before_review: boolean;
  }>;
}

/**
 * The backend range is half-open (`created_at < to`), while the screens'
 * date pickers read as inclusive: "to = today" used to exclude the whole
 * current day, and from == to was a 422. Send the day after `to`.
 */
export function exclusiveEnd(dateTo: string): string {
  const d = new Date(`${dateTo}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return dateTo;
  d.setUTCDate(d.getUTCDate() + 1);
  return d.toISOString().slice(0, 10);
}

export function getFinance(dateFrom: string, dateTo: string): Promise<FinanceSummary> {
  return apiRequest<FinanceSummary>(`/owner/finance?from=${dateFrom}&to=${exclusiveEnd(dateTo)}`);
}

export interface AnalyticsSummary {
  orders_over_time: Array<{ day: string; order_count: number; revenue: number }>;
  order_status_distribution: Record<string, number>;
  payment_status_distribution: Record<string, number>;
  best_selling_products: Array<{ variant_id: number; sku_snapshot: string; product_name_snapshot: string; total_quantity: number; total_revenue: number }>;
}

export function getAnalytics(dateFrom: string, dateTo: string): Promise<AnalyticsSummary> {
  return apiRequest<AnalyticsSummary>(`/owner/analytics?from=${dateFrom}&to=${exclusiveEnd(dateTo)}`);
}

export interface OwnerAdmin {
  id: number;
  telegram_id: number;
  first_name: string | null;
  last_name: string | null;
  username: string | null;
  status: string;
  created_at: string;
}

export function listAdmins(): Promise<{ items: OwnerAdmin[] }> {
  return apiRequest<{ items: OwnerAdmin[] }>("/owner/admins");
}

export function createAdmin(telegramId: number, firstName?: string): Promise<OwnerAdmin> {
  return apiRequest<OwnerAdmin>("/owner/admins", { method: "POST", body: { telegram_id: telegramId, first_name: firstName } });
}

export function deactivateAdmin(userId: number): Promise<OwnerAdmin> {
  return apiRequest<OwnerAdmin>(`/owner/admins/${userId}/deactivate`, { method: "POST" });
}

export function reactivateAdmin(userId: number): Promise<OwnerAdmin> {
  return apiRequest<OwnerAdmin>(`/owner/admins/${userId}/reactivate`, { method: "POST" });
}

export interface AuditLogEntry {
  id: number;
  actor_id: number | null;
  actor_role: string | null;
  action: string;
  entity_type: string;
  entity_id: number | null;
  old_data: unknown;
  new_data: unknown;
  created_at: string;
}

export function listAuditLogs(cursor?: string): Promise<{ items: AuditLogEntry[]; next_cursor: string | null }> {
  return apiRequest(`/owner/audit-logs${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ""}`);
}

export function getSettings(): Promise<Record<string, unknown>> {
  return apiRequest<Record<string, unknown>>("/owner/settings");
}

export function putSettings(settings: Record<string, unknown>): Promise<Record<string, unknown>> {
  return apiRequest<Record<string, unknown>>("/owner/settings", { method: "PUT", body: { settings } });
}
