import { apiRequest } from "./client";

export interface CartItem {
  id: number;
  cart_id: number;
  variant_id: number;
  quantity: number;
  /** Variant's base price. Never what checkout charges — see current_price. */
  price: number;
  /** §7.2-resolved price per unit, the value checkout must send back as
   *  `client_unit_price` (sending `price` 409'd on every discounted item). */
  current_price: number;
  discount_amount: number;
  sku: string;
  stock_on_hand: number;
  stock_reserved: number;
  variant_status: string;
  product_id: number;
  product_name: string;
  brand_id: number;
  /** Imzolangan asosiy rasm havolasi (ADR-13). Rasm yo'q bo'lsa null. */
  primary_image_url: string | null;
}

export function getCart(): Promise<{ items: CartItem[] }> {
  return apiRequest<{ items: CartItem[] }>("/cart");
}

export function addCartItem(variantId: number, quantity: number): Promise<unknown> {
  return apiRequest("/cart/items", { method: "POST", body: { variant_id: variantId, quantity } });
}

export function updateCartItem(itemId: number, quantity: number): Promise<unknown> {
  return apiRequest(`/cart/items/${itemId}`, { method: "PATCH", body: { quantity } });
}

export function removeCartItem(itemId: number): Promise<unknown> {
  return apiRequest(`/cart/items/${itemId}`, { method: "DELETE" });
}
