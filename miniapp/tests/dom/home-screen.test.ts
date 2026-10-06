import { describe, it, expect, vi, beforeEach } from "vitest";

const mockListProducts = vi.fn();
vi.mock("../../src/api/catalog", () => ({
  listProducts: (...args: unknown[]) => mockListProducts(...args),
}));

const mockListOrders = vi.fn();
vi.mock("../../src/api/orders", () => ({
  listOrders: (...args: unknown[]) => mockListOrders(...args),
}));

vi.mock("../../src/telegram", () => ({
  setMainButtonBusy: vi.fn(),
  resetMainButton: vi.fn(), hideBackButton: vi.fn() }));

import { render } from "../../src/screens/home";

beforeEach(() => {
  mockListProducts.mockReset();
  mockListOrders.mockReset();
  mockListOrders.mockResolvedValue({ items: [] });
});

describe("home screen", () => {
  it("shows an empty state when the catalog has no products", async () => {
    mockListProducts.mockResolvedValue({ items: [], next_cursor: null });
    const container = document.createElement("div");

    await render(container);

    expect(container.textContent).toContain("Katalog hozircha to'ldirilmoqda");
  });

  it("shows a retry button on a catalog load failure, never a blank screen", async () => {
    mockListProducts.mockRejectedValue(new Error("boom"));
    const container = document.createElement("div");

    await render(container);

    const retryButton = Array.from(container.querySelectorAll("button")).find((b) => b.textContent?.includes("urinib"));
    expect(retryButton).toBeTruthy();
  });

  it("renders product cards for a non-empty catalog", async () => {
    mockListProducts.mockResolvedValue({
      items: [{ id: 1, name: "Test Part", brand_id: 1, status: "ACTIVE", created_at: "", min_price: 10000, total_available: 3, popularity: 0 }],
      next_cursor: null,
    });
    const container = document.createElement("div");

    await render(container);

    expect(container.textContent).toContain("Test Part");
  });

  /** 1-bosqich: tepadagi tugmalar qatori pastki tab panelga ko'chdi.
   *  Ikkalasi ham chizilsa navigatsiya ikki joyda bo'lib qoladi. */
  it("no longer draws the old top action-tile row", async () => {
    mockListProducts.mockResolvedValue({ items: [], next_cursor: null });
    const container = document.createElement("div");

    await render(container);

    expect(container.querySelector(".action-grid")).toBeNull();
    expect(container.querySelector(".action-tile")).toBeNull();
  });

  /** Savat tabda yo'q, shuning uchun bosh sahifadan unga yo'l qolishi shart. */
  it("keeps a way to the cart and to the full catalog", async () => {
    mockListProducts.mockResolvedValue({ items: [], next_cursor: null });
    const container = document.createElement("div");

    await render(container);

    expect(container.querySelector('[aria-label="Savat"]')).not.toBeNull();
    expect(container.querySelector(".section-link")?.textContent).toContain("Hammasi");
  });

  it("shows a placeholder rather than a broken image for a product with no photo", async () => {
    mockListProducts.mockResolvedValue({
      items: [{ id: 1, name: "Sport sidena", brand_id: 1, status: "ACTIVE", created_at: "", min_price: 10000, total_available: 3, popularity: 0 }],
      next_cursor: null,
    });
    const container = document.createElement("div");

    await render(container);

    expect(container.querySelector(".product-card .pm-empty")).not.toBeNull();
    expect(container.querySelector(".product-card img")).toBeNull();
  });
});
