import { describe, it, expect, vi, beforeEach } from "vitest";

const mockGetCart = vi.fn();
const mockUpdateCartItem = vi.fn();
const mockRemoveCartItem = vi.fn();
vi.mock("../../src/api/cart", () => ({
  getCart: (...a: unknown[]) => mockGetCart(...a),
  addCartItem: vi.fn(),
  updateCartItem: (...a: unknown[]) => mockUpdateCartItem(...a),
  removeCartItem: (...a: unknown[]) => mockRemoveCartItem(...a),
}));

vi.mock("../../src/telegram", () => ({
  setBackButton: vi.fn(),
  setMainButton: vi.fn(),
  hideMainButton: vi.fn(),
  setMainButtonBusy: vi.fn(),
  resetMainButton: vi.fn(),
}));

import { render } from "../../src/screens/cart";

const ITEM = {
  id: 1,
  cart_id: 1,
  variant_id: 10,
  quantity: 2,
  price: 468000,
  sku: "SKU-1",
  stock_on_hand: 10,
  stock_reserved: 0,
  variant_status: "ACTIVE",
  product_id: 7,
  product_name: "Teri sidena to'plami",
  brand_id: 1,
  primary_image_url: "/files/products/7/a.webp?md5=x",
};

beforeEach(() => {
  mockGetCart.mockReset();
  mockUpdateCartItem.mockReset();
  mockRemoveCartItem.mockReset();
});

describe("cart screen", () => {
  it("shows a thumbnail for every line, not just text", async () => {
    mockGetCart.mockResolvedValue({ items: [ITEM] });
    const container = document.createElement("div");

    await render(container);

    const media = container.querySelector(".media-row .pm-72");
    expect(media).not.toBeNull();
    expect(media!.querySelector("img")?.getAttribute("src")).toContain("/files/products/7/a.webp");
  });

  it("falls back to the shared placeholder when a line has no image", async () => {
    mockGetCart.mockResolvedValue({ items: [{ ...ITEM, primary_image_url: null }] });
    const container = document.createElement("div");

    await render(container);

    expect(container.querySelector(".pm-72 .pm-empty")).not.toBeNull();
    expect(container.querySelector(".pm-letter")?.textContent).toBe("T");
  });

  it("shows the name, the price and the quantity", async () => {
    mockGetCart.mockResolvedValue({ items: [ITEM] });
    const container = document.createElement("div");

    await render(container);

    expect(container.textContent).toContain("Teri sidena to'plami");
    expect(container.querySelector(".media-row .price-now")?.textContent).toContain("468");
    expect(container.querySelector(".stepper-value")?.textContent).toBe("2");
  });

  /** Zaxiradan oshirib bo'lmaydi — server baribir rad etardi (§7.3). */
  it("disables the plus button once the line reaches available stock", async () => {
    mockGetCart.mockResolvedValue({ items: [{ ...ITEM, quantity: 10, stock_on_hand: 10, stock_reserved: 0 }] });
    const container = document.createElement("div");

    await render(container);

    const plus = Array.from(container.querySelectorAll("button")).find((b) => b.textContent === "+");
    expect((plus as HTMLButtonElement).disabled).toBe(true);
  });

  it("warns instead of showing a price when the line is no longer available", async () => {
    mockGetCart.mockResolvedValue({ items: [{ ...ITEM, quantity: 5, stock_on_hand: 1, stock_reserved: 0 }] });
    const container = document.createElement("div");

    await render(container);

    const row = container.querySelector(".media-row")!;
    expect(row.querySelector(".error-text")).not.toBeNull();
    expect(row.querySelector(".price-now")).toBeNull();
  });

  it("shows an empty state when the cart is empty", async () => {
    mockGetCart.mockResolvedValue({ items: [] });
    const container = document.createElement("div");

    await render(container);

    expect(container.querySelector(".media-row")).toBeNull();
    expect(container.textContent).toContain("Savat");
  });
});
