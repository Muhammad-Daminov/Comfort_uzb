import { describe, it, expect, vi, beforeEach } from "vitest";

const mockGetProduct = vi.fn();
vi.mock("../../src/api/catalog", () => ({
  getFilters: vi.fn().mockResolvedValue({ brands: [], colors: [], car_brands: [] }),
  getProduct: (...args: unknown[]) => mockGetProduct(...args),
}));

const mockGetCostPrice = vi.fn();
const mockSetCostPrice = vi.fn();
vi.mock("../../src/api/admin", () => ({
  adminSetProductStatus: vi.fn(),
  adminGetVariantCostPrice: (...args: unknown[]) => mockGetCostPrice(...args),
  adminSetVariantCostPrice: (...args: unknown[]) => mockSetCostPrice(...args),
  adminListCompatibilities: vi.fn().mockResolvedValue({ items: [] }),
}));
vi.mock("../../src/api/vehicles", () => ({ listCarBrands: vi.fn().mockResolvedValue({ items: [] }) }));
vi.mock("../../src/telegram", () => ({ setBackButton: vi.fn(() => () => {}) }));
vi.mock("../../src/router", () => ({ navigate: vi.fn() }));

let ownerRole = false;
vi.mock("../../src/state/session", () => ({ isOwnerRole: () => ownerRole }));

import { render } from "../../src/screens/admin/product-editor";

const PRODUCT_DETAIL = {
  product: { id: 1, name: "Malibu 2", description: null, brand_id: 1, status: "ACTIVE" },
  variants: [{ id: 42, sku: "SKU-1", price: 500000, stock_on_hand: 3, stock_reserved: 0, status: "ACTIVE" }],
  images: [],
};

beforeEach(() => {
  mockGetProduct.mockReset();
  mockGetCostPrice.mockReset();
  mockSetCostPrice.mockReset();
  mockGetProduct.mockResolvedValue(PRODUCT_DETAIL);
  ownerRole = false;
});

describe("admin product-editor — cost price visibility (§12/§13 of the v2 brief)", () => {
  it("OWNER sees the cost price row and can fetch it", async () => {
    ownerRole = true;
    mockGetCostPrice.mockResolvedValue({ id: 42, cost_price: 300000 });

    const container = document.createElement("div");
    await render(container, { id: "1" });
    await new Promise((r) => setTimeout(r, 0));

    expect(mockGetCostPrice).toHaveBeenCalledWith(42);
    expect(container.textContent).toContain("Tannarx");
  });

  it("OWNER can edit the cost price", async () => {
    ownerRole = true;
    mockGetCostPrice.mockResolvedValue({ id: 42, cost_price: 300000 });
    mockSetCostPrice.mockResolvedValue({ id: 42, cost_price: 350000 });
    (window.prompt as unknown as ReturnType<typeof vi.fn>) = vi.fn(() => "350000");

    const container = document.createElement("div");
    await render(container, { id: "1" });
    await new Promise((r) => setTimeout(r, 0));

    const editButton = Array.from(container.querySelectorAll("button")).find((b) => b.textContent === "Tahrirlash")!;
    editButton.click();
    await new Promise((r) => setTimeout(r, 0));

    expect(mockSetCostPrice).toHaveBeenCalledWith(42, 350000);
  });

  it("ADMIN (non-owner) never sees the cost price row or calls the endpoint", async () => {
    ownerRole = false;

    const container = document.createElement("div");
    await render(container, { id: "1" });
    await new Promise((r) => setTimeout(r, 0));

    expect(mockGetCostPrice).not.toHaveBeenCalled();
    expect(container.textContent).not.toContain("Tannarx");
  });
});
