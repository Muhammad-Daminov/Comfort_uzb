import { apiRequest } from "./client";

export interface CheckoutLine {
  variant_id: number;
  quantity: number;
  client_unit_price?: number;
}

export interface CancellationRequest {
  id: number;
  order_id: number;
  status: "PENDING" | "APPROVED" | "DENIED";
  reason: string;
  decision_note?: string | null;
  created_at: string;
}

export interface Refund {
  id: number;
  order_id: number;
  amount: number;
  method: "CASH" | "CARD";
  status: "PENDING" | "COMPLETED" | "FAILED";
  created_at: string;
}

export interface OrderResponse {
  id: number;
  order_number: string;
  user_id: number;
  status: string;
  total_amount: number;
  required_initial_amount: number;
  paid_amount: number;
  remaining_amount: number;
  cancellation_reason?: string | null;
  created_at: string;
  cancellation_requests?: CancellationRequest[];
  refunds?: Refund[];
}

export interface OrderListItemLine {
  product_name: string;
  quantity: number;
}

/** `GET /orders` — lighter than `OrderResponse`, only what the order-history
 *  list card needs (§P1-2): number/date/products/quantity/total/payment
 *  status/order status, no per-line unit prices. */
export interface OrderListItem {
  id: number;
  order_number: string;
  status: string;
  total_amount: number;
  paid_amount: number;
  remaining_amount: number;
  created_at: string;
  latest_payment_status: "PENDING" | "APPROVED" | "REJECTED" | null;
  items: OrderListItemLine[];
}

export function createOrder(lines: CheckoutLine[], idempotencyKey: string): Promise<OrderResponse> {
  return apiRequest<OrderResponse>("/orders", { method: "POST", body: { lines }, idempotencyKey });
}

export function listOrders(): Promise<{ items: OrderListItem[] }> {
  // GET /orders takes no query params (Phase 03) — it returns the caller's
  // orders newest-first, capped server-side. The Home screen's "most
  // recent order" link (see Context in the Phase-05 plan) just reads
  // items[0] client-side rather than asking the backend to grow a `limit`
  // param that nothing else needs.
  return apiRequest<{ items: OrderListItem[] }>("/orders");
}

export function getOrder(orderId: number): Promise<OrderResponse> {
  return apiRequest<OrderResponse>(`/orders/${orderId}`);
}

export function cancelOrder(orderId: number, reason: string): Promise<OrderResponse> {
  return apiRequest<OrderResponse>(`/orders/${orderId}/cancel`, { method: "POST", body: { reason } });
}

// ADR-017/§10: a CONFIRMED (paid) order cannot be self-cancelled — this is
// the request-then-admin-decides path instead of a direct cancel.
export function requestCancellation(orderId: number, reason: string): Promise<CancellationRequest> {
  return apiRequest<CancellationRequest>(`/orders/${orderId}/cancellation-request`, {
    method: "POST",
    body: { reason },
  });
}
