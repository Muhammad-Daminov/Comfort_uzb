import { describe, it, expect, vi, beforeEach } from "vitest";

const mockAdminListOrders = vi.fn();
const mockAdminListPayments = vi.fn();
vi.mock("../../src/api/admin", () => ({
  adminListOrders: (...args: unknown[]) => mockAdminListOrders(...args),
  adminListPayments: (...args: unknown[]) => mockAdminListPayments(...args),
}));
vi.mock("../../src/telegram", () => ({
  setMainButtonBusy: vi.fn(),
  resetMainButton: vi.fn(), setBackButton: vi.fn(() => () => {}) }));

import { render } from "../../src/screens/admin/dashboard";

beforeEach(() => {
  mockAdminListOrders.mockReset();
  mockAdminListPayments.mockReset();
});

describe("admin dashboard screen", () => {
  it("shows pending order/payment counts", async () => {
    mockAdminListOrders.mockResolvedValue({ items: [{}, {}] });
    mockAdminListPayments.mockResolvedValue({ items: [{}] });
    const container = document.createElement("div");

    await render(container);

    const statValues = Array.from(container.querySelectorAll(".stat-value")).map((el) => el.textContent);
    expect(statValues).toEqual(["2", "1"]);
    expect(container.textContent).toContain("Ko'rib chiqilishi kerak");
    expect(container.textContent).toContain("Kutilayotgan to'lovlar");
  });

  it("shows a retry button on failure, never a blank screen", async () => {
    mockAdminListOrders.mockRejectedValue(new Error("boom"));
    mockAdminListPayments.mockResolvedValue({ items: [] });
    const container = document.createElement("div");

    await render(container);

    const retryButton = Array.from(container.querySelectorAll("button")).find((b) => b.textContent?.includes("urinib"));
    expect(retryButton).toBeTruthy();
  });
});
