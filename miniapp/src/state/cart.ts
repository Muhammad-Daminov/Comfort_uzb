/**
 * Cart is server state (docs/00_MASTER_TZ.md — backend owns stock/price
 * truth). This module is a thin cache in front of `GET /cart`, invalidated
 * on every mutation response so the UI never trusts a stale local copy —
 * every add/update/remove re-fetches before the next render.
 */
import * as cartApi from "../api/cart";
import type { CartItem } from "../api/cart";

let cached: CartItem[] | null = null;
const listeners = new Set<() => void>();

export function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function notify(): void {
  for (const listener of listeners) listener();
}

export async function loadCart(): Promise<CartItem[]> {
  const response = await cartApi.getCart();
  cached = response.items;
  notify();
  return cached;
}

export function getCachedCart(): CartItem[] | null {
  return cached;
}

export async function addItem(variantId: number, quantity: number): Promise<void> {
  await cartApi.addCartItem(variantId, quantity);
  await loadCart(); // re-fetch rather than optimistically patch — price/stock at add-time is not assumed still valid
}

export async function updateItem(itemId: number, quantity: number): Promise<void> {
  await cartApi.updateCartItem(itemId, quantity);
  await loadCart();
}

export async function removeItem(itemId: number): Promise<void> {
  await cartApi.removeCartItem(itemId);
  await loadCart();
}

/** Sum of the prices checkout will actually charge (discounts applied). */
export function cartTotal(items: CartItem[]): number {
  return items.reduce((sum, item) => sum + unitPrice(item) * item.quantity, 0);
}

/** Tolerates an older backend that only sends `price`. */
export function unitPrice(item: CartItem): number {
  return typeof item.current_price === "number" ? item.current_price : item.price;
}
