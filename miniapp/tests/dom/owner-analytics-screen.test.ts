import { describe, it, expect, vi, beforeEach } from "vitest";

const mockGetAnalytics = vi.fn();
vi.mock("../../src/api/owner", () => ({
  getAnalytics: (...args: unknown[]) => mockGetAnalytics(...args),
}));
vi.mock("../../src/telegram", () => ({
  setMainButtonBusy: vi.fn(),
  resetMainButton: vi.fn(), setBackButton: vi.fn(() => () => {}) }));
vi.mock("../../src/state/session", () => ({ isOwnerRole: () => true }));

import { render } from "../../src/screens/owner/analytics";

beforeEach(() => {
  mockGetAnalytics.mockReset();
});

const SAMPLE_ANALYTICS = {
  orders_over_time: [{ day: "2026-08-01T00:00:00Z", order_count: 2, revenue: 300000 }],
  order_status_distribution: { CONFIRMED: 3, CANCELLED: 1 },
  payment_status_distribution: { APPROVED: 3 },
  best_selling_products: [
    { variant_id: 1, sku_snapshot: "SKU-1", product_name_snapshot: "Test product", total_quantity: 7, total_revenue: 700000 },
  ],
};

describe("owner analytics screen", () => {
  it("renders order status distribution, best sellers, and orders-over-time from real backend data", async () => {
    mockGetAnalytics.mockResolvedValue(SAMPLE_ANALYTICS);
    const container = document.createElement("div");

    await render(container);

    expect(container.textContent).toContain("CONFIRMED: 3");
    expect(container.textContent).toContain("Test product");
    expect(container.textContent).toContain("700 000 so'm");
    expect(container.textContent).toContain("2026-08-01");
  });

  it("shows an empty-data hint when there are no best-selling products", async () => {
    mockGetAnalytics.mockResolvedValue({ ...SAMPLE_ANALYTICS, best_selling_products: [] });
    const container = document.createElement("div");

    await render(container);

    expect(container.textContent).toContain("Ma'lumot yo'q");
  });

  it("shows a retry button on failure", async () => {
    mockGetAnalytics.mockRejectedValue(new Error("boom"));
    const container = document.createElement("div");

    await render(container);

    const retryButton = Array.from(container.querySelectorAll("button")).find((b) => b.textContent?.includes("urinib"));
    expect(retryButton).toBeTruthy();
  });
});
