import { describe, it, expect, vi, beforeEach } from "vitest";
import { ApiError } from "../../src/api/client";

const mockLoadCart = vi.fn();
vi.mock("../../src/state/cart", async () => {
  const actual = await vi.importActual<typeof import("../../src/state/cart")>("../../src/state/cart");
  return { ...actual, loadCart: (...args: unknown[]) => mockLoadCart(...args) };
});

const mockCreateOrder = vi.fn();
vi.mock("../../src/api/orders", () => ({
  createOrder: (...args: unknown[]) => mockCreateOrder(...args),
}));

const mockNavigate = vi.fn();
vi.mock("../../src/router", () => ({ navigate: (...args: unknown[]) => mockNavigate(...args) }));

let mainButtonHandler: (() => void) | null = null;
vi.mock("../../src/telegram", () => ({
  setBackButton: vi.fn(() => () => {}),
  setMainButton: vi.fn((_text: string, handler: () => void) => {
    mainButtonHandler = handler;
    return () => {};
  }),
  hideMainButton: vi.fn(),
  setMainButtonBusy: vi.fn(),
  resetMainButton: vi.fn(),
}));

import { render } from "../../src/screens/checkout";

const CART_ITEM = {
  id: 1,
  cart_id: 1,
  variant_id: 10,
  quantity: 1,
  price: 20000,
  sku: "SKU-1",
  stock_on_hand: 5,
  stock_reserved: 0,
  variant_status: "ACTIVE",
  product_id: 1,
  product_name: "Test Product",
  brand_id: 1,
};

beforeEach(() => {
  mockLoadCart.mockReset();
  mockCreateOrder.mockReset();
  mockNavigate.mockReset();
  mainButtonHandler = null;
});

describe("checkout screen", () => {
  it("navigates to the order on successful checkout", async () => {
    mockLoadCart.mockResolvedValue([CART_ITEM]);
    mockCreateOrder.mockResolvedValue({ id: 42 });
    const container = document.createElement("div");

    await render(container);
    mainButtonHandler?.();
    await new Promise((r) => setTimeout(r, 0));

    expect(mockNavigate).toHaveBeenCalledWith("/order/42");
  });

  it("shows a corrected-price notice and updates client_unit_price on 409 PRICE_MISMATCH, without silently resubmitting", async () => {
    mockLoadCart.mockResolvedValue([CART_ITEM]);

    // `lines` is mutated in place after a mismatch, so the mock must
    // snapshot (deep-clone) each call's argument immediately — reading
    // `mock.calls[i][0]` later would see the post-mutation object instead
    // of what was actually sent on that call.
    const submittedSnapshots: Array<Array<{ client_unit_price?: number }>> = [];
    mockCreateOrder.mockImplementation((lines: Array<{ client_unit_price?: number }>) => {
      submittedSnapshots.push(structuredClone(lines));
      if (submittedSnapshots.length === 1) {
        return Promise.reject(
          new ApiError("conflict", "price mismatch", 409, "PRICE_MISMATCH", {
            lines: [{ variant_id: 10, expected_unit_price: 25000 }],
          }),
        );
      }
      return Promise.resolve({ id: 43 });
    });

    const container = document.createElement("div");
    await render(container);

    mainButtonHandler?.();
    await new Promise((r) => setTimeout(r, 0));
    expect(container.textContent).toContain("Narx yangilandi");
    expect(submittedSnapshots[0][0].client_unit_price).toBe(20000); // the original, pre-correction price actually sent

    mainButtonHandler?.();
    await new Promise((r) => setTimeout(r, 0));
    expect(submittedSnapshots[1][0].client_unit_price).toBe(25000); // the corrected price, not the stale one
  });

  it("offers a way back to the cart on 409 INSUFFICIENT_STOCK", async () => {
    mockLoadCart.mockResolvedValue([CART_ITEM]);
    mockCreateOrder.mockRejectedValueOnce(
      new ApiError("conflict", "no stock", 409, "INSUFFICIENT_STOCK", null),
    );
    const container = document.createElement("div");

    await render(container);
    mainButtonHandler?.();
    await new Promise((r) => setTimeout(r, 0));

    expect(container.textContent).toContain("Savatga qaytish");
  });

  it("shows the empty-cart state and hides the main button when the cart is empty", async () => {
    mockLoadCart.mockResolvedValue([]);
    const container = document.createElement("div");

    await render(container);

    expect(container.textContent).toContain("Savatingiz bo'sh.");
    expect(mainButtonHandler).toBeNull();
  });
});

describe("checkout screen — audit regressions", () => {
  it("F2/H4: sends current_price (not the base price) as client_unit_price", async () => {
    mockLoadCart.mockResolvedValue([{ ...CART_ITEM, price: 20000, current_price: 16000, discount_amount: 4000 }]);
    mockCreateOrder.mockResolvedValue({ id: 1 });
    const container = document.createElement("div");
    await render(container);
    expect(container.textContent).toContain("16 000");
    mainButtonHandler?.();
    await new Promise((r) => setTimeout(r, 0));
    expect(mockCreateOrder.mock.calls[0][0]).toEqual([{ variant_id: 10, quantity: 1, client_unit_price: 16000 }]);
  });

  it("F6: a double tap sends one request, and a retry reuses the same Idempotency-Key", async () => {
    mockLoadCart.mockResolvedValue([CART_ITEM]);
    let rejectFirst: ((e: unknown) => void) | null = null;
    mockCreateOrder
      .mockImplementationOnce(() => new Promise((_, reject) => { rejectFirst = reject; }))
      .mockResolvedValueOnce({ id: 9 });
    const container = document.createElement("div");
    await render(container);

    mainButtonHandler?.();
    mainButtonHandler?.(); // second tap while the first is in flight
    await new Promise((r) => setTimeout(r, 0));
    expect(mockCreateOrder).toHaveBeenCalledTimes(1);

    rejectFirst!(new ApiError("network", "offline", null, null, null));
    await new Promise((r) => setTimeout(r, 0));
    const retry = container.querySelector("button");
    expect(retry).not.toBeNull();
    retry!.click();
    await new Promise((r) => setTimeout(r, 0));
    expect(mockCreateOrder).toHaveBeenCalledTimes(2);
    expect(mockCreateOrder.mock.calls[0][1]).toBe(mockCreateOrder.mock.calls[1][1]);
    expect(mockNavigate).toHaveBeenCalledWith("/order/9");
  });
});
