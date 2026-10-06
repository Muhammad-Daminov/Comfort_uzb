import { describe, it, expect, vi, beforeEach } from "vitest";

const mockGetFilters = vi.fn();
const mockGetProduct = vi.fn();
const mockAdminCreateProduct = vi.fn();
const mockAdminSetProductStatus = vi.fn();
vi.mock("../../src/api/catalog", () => ({
  getFilters: (...args: unknown[]) => mockGetFilters(...args),
  getProduct: (...args: unknown[]) => mockGetProduct(...args),
}));
vi.mock("../../src/api/admin", () => ({
  adminCreateProduct: (...args: unknown[]) => mockAdminCreateProduct(...args),
  adminSetProductStatus: (...args: unknown[]) => mockAdminSetProductStatus(...args),
  adminListCompatibilities: vi.fn().mockResolvedValue({ items: [] }),
}));
vi.mock("../../src/api/vehicles", () => ({
  listCarBrands: vi.fn().mockResolvedValue({ items: [] }),
  listCarModels: vi.fn().mockResolvedValue({ items: [] }),
  listCarGenerations: vi.fn().mockResolvedValue({ items: [] }),
}));
vi.mock("../../src/telegram", () => ({
  setMainButtonBusy: vi.fn(),
  resetMainButton: vi.fn(), setBackButton: vi.fn(() => () => {}) }));
const mockNavigate = vi.fn();
vi.mock("../../src/router", () => ({ navigate: (...args: unknown[]) => mockNavigate(...args) }));

import { render } from "../../src/screens/admin/product-editor";

beforeEach(() => {
  mockGetFilters.mockReset();
  mockGetProduct.mockReset();
  mockAdminCreateProduct.mockReset();
  mockAdminSetProductStatus.mockReset();
  mockNavigate.mockReset();
  mockGetFilters.mockResolvedValue({ brands: [{ id: 1, name: "Brand A" }], colors: [], car_brands: [] });
});

describe("admin product-editor screen — create mode", () => {
  it("rejects submission with an empty name, never calling the backend", async () => {
    const container = document.createElement("div");
    await render(container, { id: "new" });

    const createButton = Array.from(container.querySelectorAll("button")).find((b) => b.textContent === "Yaratish")!;
    createButton.click();
    await new Promise((r) => setTimeout(r, 0));

    expect(mockAdminCreateProduct).not.toHaveBeenCalled();
  });

  it("creates the product and navigates to its editor on valid input", async () => {
    mockAdminCreateProduct.mockResolvedValue({ id: 42, name: "New Product" });
    const container = document.createElement("div");
    await render(container, { id: "new" });

    const nameInput = container.querySelector("input") as HTMLInputElement;
    nameInput.value = "New Product";

    const createButton = Array.from(container.querySelectorAll("button")).find((b) => b.textContent === "Yaratish")!;
    createButton.click();
    await new Promise((r) => setTimeout(r, 0));

    expect(mockAdminCreateProduct).toHaveBeenCalledWith("New Product", 1, undefined, "SIDENA");
    expect(mockNavigate).toHaveBeenCalledWith("/admin/product/42");
  });
});

describe("admin product-editor screen — edit mode: status-chip mutation failure", () => {
  const detail = {
    product: { id: 7, name: "Existing Product", status: "DRAFT", product_type: "SIDENA" },
    variants: [],
    images: [],
  };

  it("re-enables the chip and shows an error instead of leaving it disabled forever", async () => {
    mockGetProduct.mockResolvedValue(detail);
    mockAdminSetProductStatus.mockRejectedValue(new Error("network error"));

    const container = document.createElement("div");
    await render(container, { id: "7" });

    const statusChip = Array.from(container.querySelectorAll("button")).find((b) => b.textContent === "→ ACTIVE")!;
    statusChip.click();
    expect(statusChip.disabled).toBe(true); // immediately disabled while the request is in flight

    await new Promise((r) => setTimeout(r, 0));

    expect(mockAdminSetProductStatus).toHaveBeenCalledWith(7, "ACTIVE");
    expect(statusChip.disabled).toBe(false); // re-enabled after the failure — not stuck forever
    expect(container.textContent).toMatch(/network error|xatolik|Xatolik/i);
  });
});
