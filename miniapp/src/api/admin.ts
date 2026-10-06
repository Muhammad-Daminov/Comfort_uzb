import { apiRequest } from "./client";
import type { CancellationRequest, OrderResponse, Refund } from "./orders";
import type { PaymentResponse } from "./payments";

// --- Orders/Payments (reusing Phase 03 endpoints, admin-scoped) -----------

const ADMIN_LIST_LIMIT = 200; // backend max; the default of 20 capped the dashboard counters at "20 ta"

export function adminListOrders(status?: string): Promise<{ items: OrderResponse[] }> {
  const query = new URLSearchParams({ limit: String(ADMIN_LIST_LIMIT) });
  if (status) query.set("status", status);
  return apiRequest<{ items: OrderResponse[] }>(`/admin/orders?${query.toString()}`);
}

export function adminConfirmOrder(orderId: number, idempotencyKey: string): Promise<OrderResponse> {
  return apiRequest<OrderResponse>(`/admin/orders/${orderId}/confirm`, { method: "POST", idempotencyKey });
}

export function adminCancelOrder(orderId: number, reason: string, idempotencyKey: string): Promise<OrderResponse> {
  return apiRequest<OrderResponse>(`/admin/orders/${orderId}/cancel`, {
    method: "POST",
    body: { reason },
    idempotencyKey,
  });
}

export function adminListPayments(status?: string): Promise<{ items: PaymentResponse[] }> {
  const query = new URLSearchParams({ limit: String(ADMIN_LIST_LIMIT) });
  if (status) query.set("status", status);
  return apiRequest<{ items: PaymentResponse[] }>(`/admin/payments?${query.toString()}`);
}

export function adminReviewPayment(
  paymentId: number,
  approve: boolean,
  rejectionReason?: string,
): Promise<PaymentResponse> {
  return apiRequest<PaymentResponse>(`/admin/payments/${paymentId}/review`, {
    method: "POST",
    body: { approve, rejection_reason: rejectionReason },
  });
}

export function adminGetReceiptUrl(paymentId: number): Promise<{ url: string }> {
  return apiRequest<{ url: string }>(`/admin/payments/${paymentId}/receipt`);
}

// --- Cancellation requests / refunds (ADR-017) ------------------------------

export function adminListCancellationRequests(): Promise<{ items: CancellationRequest[] }> {
  return apiRequest<{ items: CancellationRequest[] }>("/admin/cancellation-requests");
}

export function adminApproveCancellationRequest(requestId: number, decisionNote?: string): Promise<CancellationRequest> {
  return apiRequest<CancellationRequest>(`/admin/cancellation-requests/${requestId}/approve`, {
    method: "POST",
    body: { decision_note: decisionNote },
  });
}

export function adminDenyCancellationRequest(requestId: number, decisionNote?: string): Promise<CancellationRequest> {
  return apiRequest<CancellationRequest>(`/admin/cancellation-requests/${requestId}/deny`, {
    method: "POST",
    body: { decision_note: decisionNote },
  });
}

export function adminRecordRefund(
  orderId: number,
  amount: number,
  method: "CASH" | "CARD",
  reason: string,
): Promise<Refund> {
  return apiRequest<Refund>("/admin/refunds", {
    method: "POST",
    body: { order_id: orderId, amount, method, reason },
  });
}

export function adminCompleteRefund(refundId: number, providerReference?: string): Promise<Refund> {
  return apiRequest<Refund>(`/admin/refunds/${refundId}/complete`, {
    method: "POST",
    body: { provider_reference: providerReference },
  });
}

export function adminAdjustInventory(
  variantId: number,
  quantityChange: number,
  reason: string,
  idempotencyKey: string,
): Promise<unknown> {
  return apiRequest("/admin/inventory/adjust", {
    method: "POST",
    body: { variant_id: variantId, quantity_change: quantityChange, reason },
    idempotencyKey,
  });
}

// --- Products / variants ----------------------------------------------------

/** SIDENA (sidena) or SIDENA_COVER (sidena chexoli) — the business's exact
 * current scope (§P1-3), matches the backend CHECK constraint. */
export type ProductType = "SIDENA" | "SIDENA_COVER";

export interface AdminProduct {
  id: number;
  name: string;
  description: string | null;
  brand_id: number;
  status: string;
  source: string;
  product_type: ProductType | null;
  created_at: string;
  updated_at: string;
}

export interface AdminVariant {
  id: number;
  product_id: number;
  sku: string;
  color_id: number | null;
  material: string | null;
  price: number;
  required_initial_payment: number;
  stock_on_hand: number;
  stock_reserved: number;
  status: string;
}

export function adminCreateProduct(
  name: string,
  brandId: number,
  description?: string,
  productType?: ProductType,
): Promise<AdminProduct> {
  return apiRequest<AdminProduct>("/admin/products", {
    method: "POST",
    body: { name, brand_id: brandId, description, product_type: productType },
  });
}

export function adminUpdateProduct(
  productId: number,
  fields: { name?: string; description?: string; brand_id?: number; product_type?: ProductType },
): Promise<AdminProduct> {
  return apiRequest<AdminProduct>(`/admin/products/${productId}`, { method: "PATCH", body: fields });
}

export function adminSetProductStatus(productId: number, status: string): Promise<AdminProduct> {
  return apiRequest<AdminProduct>(`/admin/products/${productId}/status`, { method: "POST", body: { status } });
}

export function adminCreateVariant(
  productId: number,
  sku: string,
  price: number,
  colorId?: number,
  requiredInitialPayment = 0,
  material?: string,
): Promise<AdminVariant> {
  return apiRequest<AdminVariant>("/admin/variants", {
    method: "POST",
    body: {
      product_id: productId, sku, price, color_id: colorId,
      required_initial_payment: requiredInitialPayment, material,
    },
  });
}

export function adminUpdateVariant(
  variantId: number,
  fields: { sku?: string; color_id?: number; price?: number; required_initial_payment?: number; material?: string },
): Promise<AdminVariant> {
  return apiRequest<AdminVariant>(`/admin/variants/${variantId}`, { method: "PATCH", body: fields });
}

export function adminSetVariantStatus(variantId: number, status: string): Promise<AdminVariant> {
  return apiRequest<AdminVariant>(`/admin/variants/${variantId}/status`, { method: "POST", body: { status } });
}

// --- Cost price (OWNER only — finance.view; §12/§13 of the v2 brief) -------

export function adminGetVariantCostPrice(variantId: number): Promise<{ id: number; cost_price: number | null }> {
  return apiRequest(`/admin/variants/${variantId}/cost-price`);
}

export function adminSetVariantCostPrice(variantId: number, costPrice: number): Promise<{ id: number; cost_price: number }> {
  return apiRequest(`/admin/variants/${variantId}/cost-price`, { method: "PATCH", body: { cost_price: costPrice } });
}

// --- Brands / colors ---------------------------------------------------------

export function adminCreateBrand(name: string): Promise<{ id: number; name: string }> {
  return apiRequest("/admin/brands", { method: "POST", body: { name } });
}

// --- Images ------------------------------------------------------------------

export interface AdminImage {
  id: number;
  product_id: number;
  storage_path: string;
  sort_order: number;
  is_primary: boolean;
  width: number;
  height: number;
}

export function adminAddImage(productId: number, file: File): Promise<AdminImage> {
  const formData = new FormData();
  formData.append("file", file);
  return apiRequest<AdminImage>(`/admin/products/${productId}/images`, { method: "POST", body: formData, isFormData: true });
}

export function adminRemoveImage(productId: number, imageId: number): Promise<unknown> {
  return apiRequest(`/admin/products/${productId}/images/${imageId}`, { method: "DELETE" });
}

export function adminSetPrimaryImage(productId: number, imageId: number): Promise<unknown> {
  return apiRequest(`/admin/products/${productId}/images/${imageId}/primary`, { method: "POST" });
}

export function adminReorderImages(productId: number, imageIds: number[]): Promise<{ image_ids: number[] }> {
  return apiRequest(`/admin/products/${productId}/images/order`, { method: "PATCH", body: { image_ids: imageIds } });
}

// --- Vehicle compatibility -----------------------------------------------------

export interface AdminCompatibility {
  id: number;
  product_id: number;
  generation_id: number;
  year_from: number | null;
  year_to: number | null;
  note: string | null;
}

export function adminListCompatibilities(productId: number): Promise<{ items: AdminCompatibility[] }> {
  return apiRequest<{ items: AdminCompatibility[] }>(`/admin/products/${productId}/compatibilities`);
}

export function adminAddCompatibility(
  productId: number,
  generationId: number,
  yearFrom?: number,
  yearTo?: number,
  note?: string,
): Promise<AdminCompatibility> {
  return apiRequest<AdminCompatibility>(`/admin/products/${productId}/compatibilities`, {
    method: "POST",
    body: { generation_id: generationId, year_from: yearFrom, year_to: yearTo, note },
  });
}

export function adminRemoveCompatibility(productId: number, compatibilityId: number): Promise<unknown> {
  return apiRequest(`/admin/products/${productId}/compatibilities/${compatibilityId}`, { method: "DELETE" });
}
