import { describe, it, expect, vi, beforeEach } from "vitest";

const mockGetCart = vi.fn();
const mockAddCartItem = vi.fn();
const mockUpdateCartItem = vi.fn();
const mockRemoveCartItem = vi.fn();

vi.mock("../../src/api/cart", () => ({
  getCart: (...args: unknown[]) => mockGetCart(...args),
  addCartItem: (...args: unknown[]) => mockAddCartItem(...args),
  updateCartItem: (...args: unknown[]) => mockUpdateCartItem(...args),
  removeCartItem: (...args: unknown[]) => mockRemoveCartItem(...args),
}));

import * as cartState from "../../src/state/cart";

const ITEM = {
  id: 1,
  cart_id: 1,
  variant_id: 10,
  quantity: 2,
  price: 5000,
  current_price: 5000,
  discount_amount: 0,
  sku: "SKU-1",
  stock_on_hand: 10,
  stock_reserved: 0,
  variant_status: "ACTIVE",
  product_id: 1,
  product_name: "Test Product",
  brand_id: 1,
  primary_image_url: null,
};

beforeEach(() => {
  mockGetCart.mockReset();
  mockAddCartItem.mockReset();
  mockUpdateCartItem.mockReset();
  mockRemoveCartItem.mockReset();
});

describe("cart state", () => {
  it("re-fetches the cart after adding an item, rather than trusting a local patch", async () => {
    mockAddCartItem.mockResolvedValue({});
    mockGetCart.mockResolvedValue({ items: [ITEM] });

    await cartState.addItem(10, 2);

    expect(mockAddCartItem).toHaveBeenCalledWith(10, 2);
    expect(mockGetCart).toHaveBeenCalledTimes(1); // the re-fetch, not an optimistic in-memory update
    expect(cartState.getCachedCart()).toEqual([ITEM]);
  });

  it("re-fetches after removing an item", async () => {
    mockRemoveCartItem.mockResolvedValue({});
    mockGetCart.mockResolvedValue({ items: [] });

    await cartState.removeItem(1);

    expect(mockGetCart).toHaveBeenCalledTimes(1);
    expect(cartState.getCachedCart()).toEqual([]);
  });

  it("notifies subscribers on every load", async () => {
    mockGetCart.mockResolvedValue({ items: [ITEM] });
    const listener = vi.fn();
    const unsubscribe = cartState.subscribe(listener);

    await cartState.loadCart();

    expect(listener).toHaveBeenCalledTimes(1);
    unsubscribe();
  });

  it("computes cart total from price * quantity across items", () => {
    const total = cartState.cartTotal([ITEM, { ...ITEM, id: 2, price: 1000, current_price: 1000, quantity: 3 }]);
    expect(total).toBe(5000 * 2 + 1000 * 3);
  });

  it("totals the discounted current_price, not the base price (audit H4)", () => {
    const discounted = { ...ITEM, id: 3, price: 5000, current_price: 4000, discount_amount: 1000, quantity: 2 };
    expect(cartState.cartTotal([discounted])).toBe(8000);
    expect(cartState.unitPrice(discounted)).toBe(4000);
  });

  it("falls back to price when a backend omits current_price", () => {
    const legacy = { ...ITEM, current_price: undefined as unknown as number };
    expect(cartState.unitPrice(legacy)).toBe(5000);
  });
});
