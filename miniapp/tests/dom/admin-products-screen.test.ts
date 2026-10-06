import { describe, it, expect, vi, beforeEach } from "vitest";

const mockListProducts = vi.fn();
vi.mock("../../src/api/catalog", () => ({ listProducts: (...a: unknown[]) => mockListProducts(...a) }));

const mockSetStatus = vi.fn();
vi.mock("../../src/api/admin", () => ({ adminSetProductStatus: (...a: unknown[]) => mockSetStatus(...a) }));

vi.mock("../../src/telegram", () => ({
  setMainButtonBusy: vi.fn(),
  resetMainButton: vi.fn(), setBackButton: vi.fn() }));

import { render } from "../../src/screens/admin/products";

const PRODUCT = {
  id: 7,
  name: "Teri sidena to'plami",
  brand_id: 1,
  status: "ACTIVE",
  created_at: "",
  min_price: 468000,
  total_available: 5,
  popularity: 0,
  primary_image_url: "/files/products/7/a.webp?md5=x",
};

beforeEach(() => {
  mockListProducts.mockReset();
  mockSetStatus.mockReset();
});

describe("admin products screen", () => {
  it("shows a thumbnail, the name, the price and the stock on one row", async () => {
    mockListProducts.mockResolvedValue({ items: [PRODUCT], next_cursor: null });
    const container = document.createElement("div");

    await render(container);

    const row = container.querySelector(".media-row")!;
    expect(row.querySelector(".pm-56 img")?.getAttribute("src")).toContain("/files/products/7/a.webp");
    expect(row.textContent).toContain("Teri sidena to'plami");
    expect(row.textContent).toContain("468");
    expect(row.textContent).toContain("Stok: 5");
  });

  it("uses the shared placeholder when a product has no image", async () => {
    mockListProducts.mockResolvedValue({ items: [{ ...PRODUCT, primary_image_url: null }], next_cursor: null });
    const container = document.createElement("div");

    await render(container);

    expect(container.querySelector(".pm-56 .pm-empty")).not.toBeNull();
  });

  it("labels a sold-out product instead of showing 'Stok: 0'", async () => {
    mockListProducts.mockResolvedValue({ items: [{ ...PRODUCT, total_available: 0 }], next_cursor: null });
    const container = document.createElement("div");

    await render(container);

    expect(container.querySelector(".badge-dang")?.textContent).toBe("Tugagan");
  });

  it("offers an edit and an archive action on every row", async () => {
    mockListProducts.mockResolvedValue({ items: [PRODUCT], next_cursor: null });
    const container = document.createElement("div");

    await render(container);

    const labels = Array.from(container.querySelectorAll(".media-row-actions button")).map((b) =>
      b.getAttribute("aria-label"),
    );
    expect(labels).toEqual(["Teri sidena to'plami — tahrirlash", "Teri sidena to'plami — arxivlash"]);
  });

  /** Arxivlash qaytarib bo'lmaydigan ko'rinadi — tasdiqsiz bajarilmaydi. */
  it("does not archive when the admin cancels the confirmation", async () => {
    mockListProducts.mockResolvedValue({ items: [PRODUCT], next_cursor: null });
    const container = document.createElement("div");
    await render(container);

    vi.spyOn(window, "confirm").mockReturnValue(false);
    container.querySelector<HTMLButtonElement>('[aria-label$="arxivlash"]')!.click();

    expect(mockSetStatus).not.toHaveBeenCalled();
  });

  it("archives with the ARCHIVED status once confirmed", async () => {
    mockListProducts.mockResolvedValue({ items: [PRODUCT], next_cursor: null });
    mockSetStatus.mockResolvedValue({});
    const container = document.createElement("div");
    await render(container);

    vi.spyOn(window, "confirm").mockReturnValue(true);
    container.querySelector<HTMLButtonElement>('[aria-label$="arxivlash"]')!.click();

    expect(mockSetStatus).toHaveBeenCalledWith(7, "ARCHIVED");
  });
});
