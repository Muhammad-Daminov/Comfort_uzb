import { describe, it, expect, vi, beforeEach } from "vitest";

const mockGetFinance = vi.fn();
vi.mock("../../src/api/owner", () => ({
  getFinance: (...args: unknown[]) => mockGetFinance(...args),
}));
vi.mock("../../src/telegram", () => ({
  setMainButtonBusy: vi.fn(),
  resetMainButton: vi.fn(), setBackButton: vi.fn(() => () => {}) }));
vi.mock("../../src/state/session", () => ({ isOwnerRole: () => true }));

import { render } from "../../src/screens/owner/finance";

beforeEach(() => {
  mockGetFinance.mockReset();
});

const SAMPLE_FINANCE = {
  revenue: 500000,
  order_count: 4,
  payment_status_breakdown: [{ status: "APPROVED", count: 3, total_amount: 450000 }],
  payments: [
    { payment_id: 1, order_id: 10, amount: 150000, status: "APPROVED", submitted_at: "2026-08-01T00:00:00Z", hidden_before_review: false },
  ],
};

describe("owner finance screen", () => {
  it("renders revenue, order count, and payment breakdown from real backend data", async () => {
    mockGetFinance.mockResolvedValue(SAMPLE_FINANCE);
    const container = document.createElement("div");

    await render(container);

    expect(mockGetFinance).toHaveBeenCalled();
    expect(container.textContent).toContain("500 000 so'm");
    expect(container.textContent).toContain("APPROVED: 3 ta");
    expect(container.textContent).toContain("#1");
  });

  it("shows the hidden-before-review warning on flagged payments", async () => {
    mockGetFinance.mockResolvedValue({
      ...SAMPLE_FINANCE,
      payments: [{ ...SAMPLE_FINANCE.payments[0], hidden_before_review: true }],
    });
    const container = document.createElement("div");

    await render(container);

    expect(container.textContent).toContain("tekshiruvdan oldin yashirilgan");
  });

  it("re-fetches with the selected date range when the filter button is clicked", async () => {
    mockGetFinance.mockResolvedValue(SAMPLE_FINANCE);
    const container = document.createElement("div");

    await render(container);
    mockGetFinance.mockClear();

    const [fromInput, toInput] = Array.from(container.querySelectorAll("input"));
    fromInput.value = "2026-01-01";
    toInput.value = "2026-01-31";
    const filterButton = Array.from(container.querySelectorAll("button")).find((b) => b.textContent === "Ko'rish");
    filterButton?.click();
    await Promise.resolve();
    await Promise.resolve();

    expect(mockGetFinance).toHaveBeenCalledWith("2026-01-01", "2026-01-31");
  });

  it("shows a retry button on failure", async () => {
    mockGetFinance.mockRejectedValue(new Error("boom"));
    const container = document.createElement("div");

    await render(container);

    const retryButton = Array.from(container.querySelectorAll("button")).find((b) => b.textContent?.includes("urinib"));
    expect(retryButton).toBeTruthy();
  });
});
