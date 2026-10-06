import { describe, it, expect, vi, beforeEach } from "vitest";
import { ApiError } from "../../src/api/client";

const mockGetOrder = vi.fn();
vi.mock("../../src/api/orders", () => ({
  getOrder: (...args: unknown[]) => mockGetOrder(...args),
}));

const mockSubmitPayment = vi.fn();
vi.mock("../../src/api/payments", () => ({
  submitPayment: (...args: unknown[]) => mockSubmitPayment(...args),
}));

const mockNavigate = vi.fn();
vi.mock("../../src/router", () => ({ navigate: (...args: unknown[]) => mockNavigate(...args) }));

let mainButtonHandler: (() => void) | null = null;
vi.mock("../../src/telegram", () => ({
  setMainButtonBusy: vi.fn(),
  resetMainButton: vi.fn(),
  setBackButton: vi.fn(() => () => {}),
  setMainButton: vi.fn((_text: string, handler: () => void) => {
    mainButtonHandler = handler;
    return () => {};
  }),
}));

import { render } from "../../src/screens/payment";

const ORDER = {
  id: 42,
  order_number: "ORD-42",
  user_id: 1,
  status: "AWAITING_PAYMENT",
  total_amount: 100000,
  required_initial_amount: 100000,
  paid_amount: 0,
  remaining_amount: 100000,
  created_at: "2026-08-01T00:00:00Z",
};

beforeEach(() => {
  mockGetOrder.mockReset();
  mockSubmitPayment.mockReset();
  mockNavigate.mockReset();
  mainButtonHandler = null;
});

describe("payment screen", () => {
  it("renders the amount due from real backend data", async () => {
    mockGetOrder.mockResolvedValue(ORDER);
    const container = document.createElement("div");

    await render(container, { orderId: "42" });

    expect(mockGetOrder).toHaveBeenCalledWith(42);
    expect(container.textContent).toContain("100 000 so'm");
    expect(mainButtonHandler).toBeTruthy();
  });

  it("navigates to the receipt upload screen after a successful submit", async () => {
    mockGetOrder.mockResolvedValue(ORDER);
    mockSubmitPayment.mockResolvedValue({ id: 7 });
    const container = document.createElement("div");

    await render(container, { orderId: "42" });
    mainButtonHandler?.();
    await new Promise((r) => setTimeout(r, 0));

    expect(mockNavigate).toHaveBeenCalledWith("/receipt/7");
  });

  it("shows a retry button when the order fails to load", async () => {
    mockGetOrder.mockRejectedValueOnce(new Error("boom")).mockResolvedValueOnce(ORDER);
    const container = document.createElement("div");

    await render(container, { orderId: "42" });

    const retryButton = Array.from(container.querySelectorAll("button")).find((b) => b.textContent?.includes("urinib"));
    expect(retryButton).toBeTruthy();

    retryButton?.click();
    await new Promise((r) => setTimeout(r, 0));

    expect(container.textContent).toContain("100 000 so'm");
  });

  it("shows a retry button when payment submission fails", async () => {
    mockGetOrder.mockResolvedValue(ORDER);
    mockSubmitPayment.mockRejectedValueOnce(new ApiError("server_error", "boom", 500, null, null));
    const container = document.createElement("div");

    await render(container, { orderId: "42" });
    mainButtonHandler?.();
    await new Promise((r) => setTimeout(r, 0));

    const retryButton = Array.from(container.querySelectorAll("button")).find((b) => b.textContent?.includes("urinib"));
    expect(retryButton).toBeTruthy();
  });
});
