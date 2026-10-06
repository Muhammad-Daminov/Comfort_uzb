import { describe, it, expect, vi, beforeEach } from "vitest";

const mockGetDashboard = vi.fn();
vi.mock("../../src/api/owner", () => ({
  getDashboard: (...args: unknown[]) => mockGetDashboard(...args),
}));
vi.mock("../../src/telegram", () => ({
  setMainButtonBusy: vi.fn(),
  resetMainButton: vi.fn(), setBackButton: vi.fn(() => () => {}) }));
vi.mock("../../src/state/session", () => ({ isOwnerRole: () => true }));

import { render } from "../../src/screens/owner/dashboard";

beforeEach(() => {
  mockGetDashboard.mockReset();
});

const SAMPLE_SUMMARY = {
  order_counts_by_status: { CONFIRMED: 3, UNDER_REVIEW: 1 },
  total_revenue: 150000,
  product_count: 10,
  active_product_count: 8,
  low_stock_threshold: 5,
  low_stock_variants: [],
  recent_orders: [],
  recent_payments: [],
};

describe("owner dashboard screen", () => {
  it("renders revenue and product counts from real backend data", async () => {
    mockGetDashboard.mockResolvedValue(SAMPLE_SUMMARY);
    const container = document.createElement("div");

    await render(container);

    expect(container.textContent).toContain("150 000 so'm");
    expect(container.textContent).toContain("8/10");
    expect(container.textContent).toContain("Faol / jami mahsulot");
  });

  it("shows low-stock warning when present", async () => {
    mockGetDashboard.mockResolvedValue({
      ...SAMPLE_SUMMARY,
      low_stock_variants: [{ variant_id: 1, sku: "SKU-1", product_name: "Test", available: 2 }],
    });
    const container = document.createElement("div");

    await render(container);

    expect(container.textContent).toContain("Kam qolgan");
    expect(container.textContent).toContain("SKU-1");
  });

  it("shows a retry button on failure", async () => {
    mockGetDashboard.mockRejectedValue(new Error("boom"));
    const container = document.createElement("div");

    await render(container);

    const retryButton = Array.from(container.querySelectorAll("button")).find((b) => b.textContent?.includes("urinib"));
    expect(retryButton).toBeTruthy();
  });
});
