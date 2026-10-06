import { describe, it, expect, vi, beforeEach } from "vitest";

const mockGetFilters = vi.fn();
const mockAdminCreateProduct = vi.fn();
vi.mock("../../src/api/catalog", () => ({
  getFilters: (...args: unknown[]) => mockGetFilters(...args),
  getProduct: vi.fn(),
}));
vi.mock("../../src/api/admin", () => ({
  adminCreateProduct: (...args: unknown[]) => mockAdminCreateProduct(...args),
}));
vi.mock("../../src/api/vehicles", () => ({}));
vi.mock("../../src/telegram", () => ({
  setMainButtonBusy: vi.fn(),
  resetMainButton: vi.fn(), setBackButton: vi.fn(() => () => {}) }));
const mockNavigate = vi.fn();
vi.mock("../../src/router", () => ({ navigate: (...args: unknown[]) => mockNavigate(...args) }));

import { render } from "../../src/screens/admin/product-editor";

beforeEach(() => {
  mockGetFilters.mockReset();
  mockAdminCreateProduct.mockReset();
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
