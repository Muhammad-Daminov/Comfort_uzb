import { apiRequest } from "./client";

export type DiscountKind = "PERCENT" | "FIXED";
export type DiscountTargetType = "VARIANT" | "PRODUCT" | "BRAND" | "CAR_MODEL" | "ALL";

export interface DiscountTarget {
  id: number;
  discount_id: number;
  target_type: DiscountTargetType;
  target_id: number | null;
}

export interface Discount {
  id: number;
  name: string;
  kind: DiscountKind;
  value: number;
  starts_at: string | null;
  ends_at: string | null;
  is_active: boolean;
  priority: number;
  created_at: string;
  updated_at: string;
  targets: DiscountTarget[];
}

export function listDiscounts(): Promise<{ items: Discount[] }> {
  return apiRequest<{ items: Discount[] }>("/owner/discounts");
}

export function createDiscount(body: {
  name: string;
  kind: DiscountKind;
  value: number;
  starts_at?: string | null;
  ends_at?: string | null;
  priority?: number;
  targets: Array<{ target_type: DiscountTargetType; target_id: number | null }>;
}): Promise<Discount> {
  return apiRequest<Discount>("/owner/discounts", { method: "POST", body });
}

export function updateDiscount(
  discountId: number,
  body: { name?: string; kind?: DiscountKind; value?: number; priority?: number },
): Promise<Discount> {
  return apiRequest<Discount>(`/owner/discounts/${discountId}`, { method: "PATCH", body });
}

export function setDiscountActive(discountId: number, isActive: boolean): Promise<Discount> {
  return apiRequest<Discount>(`/owner/discounts/${discountId}/status`, {
    method: "POST",
    body: { is_active: isActive },
  });
}

export function addDiscountTarget(
  discountId: number,
  targetType: DiscountTargetType,
  targetId: number | null,
): Promise<DiscountTarget> {
  return apiRequest<DiscountTarget>(`/owner/discounts/${discountId}/targets`, {
    method: "POST",
    body: { target_type: targetType, target_id: targetId },
  });
}

export function removeDiscountTarget(discountId: number, rowId: number): Promise<unknown> {
  return apiRequest(`/owner/discounts/${discountId}/targets/${rowId}`, { method: "DELETE" });
}
