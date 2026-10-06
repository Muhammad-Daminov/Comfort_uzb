import { describe, it, expect, vi, beforeEach } from "vitest";

const mockAdminListOrders = vi.fn();
vi.mock("../../src/api/admin", () => ({
  adminListOrders: (...args: unknown[]) => mockAdminListOrders(...args),
}));
vi.mock("../../src/telegram", () => ({
  setMainButtonBusy: vi.fn(),
  resetMainButton: vi.fn(), setBackButton: vi.fn(() => () => {}) }));

import { render } from "../../src/screens/admin/orders";

beforeEach(() => {
  mockAdminListOrders.mockReset();
});

describe("admin orders screen", () => {
  it("defaults to the UNDER_REVIEW filter on load", async () => {
    mockAdminListOrders.mockResolvedValue({ items: [] });
    const container = document.createElement("div");

    await render(container);

    expect(mockAdminListOrders).toHaveBeenCalledWith("UNDER_REVIEW");
  });

  it("shows an empty state when there are no orders in the selected status", async () => {
    mockAdminListOrders.mockResolvedValue({ items: [] });
    const container = document.createElement("div");

    await render(container);

    expect(container.textContent).toContain("Bu holatda buyurtmalar yo'q");
  });

  it("renders one row per order with its number and status", async () => {
    mockAdminListOrders.mockResolvedValue({
      items: [
        {
          id: 1,
          order_number: "CU-ABC123",
          status: "UNDER_REVIEW",
          total_amount: 50000,
          created_at: "2026-01-15T00:00:00Z",
        },
      ],
    });
    const container = document.createElement("div");

    await render(container);

    expect(container.textContent).toContain("CU-ABC123");
    // Admin now shows the same human-readable Uzbek status label the
    // user-facing orders screen already uses (src/screens/orders.ts),
    // not the raw backend enum string.
    expect(container.textContent).toContain("Ko'rib chiqilmoqda");
  });
});
