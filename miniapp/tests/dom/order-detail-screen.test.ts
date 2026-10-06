import { describe, it, expect, vi, beforeEach } from "vitest";

const mockGetOrder = vi.fn();
const mockCancelOrder = vi.fn();
const mockRequestCancellation = vi.fn();
vi.mock("../../src/api/orders", () => ({
  getOrder: (...args: unknown[]) => mockGetOrder(...args),
  cancelOrder: (...args: unknown[]) => mockCancelOrder(...args),
  requestCancellation: (...args: unknown[]) => mockRequestCancellation(...args),
}));

const mockNavigate = vi.fn();
vi.mock("../../src/router", () => ({ navigate: (...args: unknown[]) => mockNavigate(...args) }));

let mainButtonHandler: (() => void) | null = null;
vi.mock("../../src/telegram", () => ({
  setBackButton: vi.fn(() => () => {}),
  setMainButton: vi.fn((_text: string, handler: () => void) => {
    mainButtonHandler = handler;
    return () => {};
  }),
  hideMainButton: vi.fn(),
}));

import { render } from "../../src/screens/order-detail";

const BASE_ORDER = {
  id: 7,
  order_number: "ORD-7",
  user_id: 1,
  total_amount: 100000,
  required_initial_amount: 100000,
  paid_amount: 100000,
  remaining_amount: 0,
  created_at: "2026-09-01T00:00:00Z",
};

beforeEach(() => {
  mockGetOrder.mockReset();
  mockCancelOrder.mockReset();
  mockRequestCancellation.mockReset();
  mockNavigate.mockReset();
  mainButtonHandler = null;
});

describe("order detail screen — post-confirmation cancellation (ADR-017)", () => {
  it("offers 'request cancellation' (not direct cancel) for a CONFIRMED paid order", async () => {
    mockGetOrder.mockResolvedValue({ ...BASE_ORDER, status: "CONFIRMED", cancellation_requests: [], refunds: [] });
    const container = document.createElement("div");
    await render(container, { id: "7" });

    // No direct "cancel" button should exist for a CONFIRMED order.
    const buttons = Array.from(container.querySelectorAll("button")).map((b) => b.textContent);
    expect(buttons).not.toContain("Buyurtmani bekor qilish");

    expect(mainButtonHandler).not.toBeNull();
    (window.prompt as unknown as ReturnType<typeof vi.fn>) = vi.fn(() => "wrong color, want to return it");
    mockRequestCancellation.mockResolvedValue({ id: 1, order_id: 7, status: "PENDING", reason: "x", created_at: "x" });
    mockGetOrder.mockResolvedValue({
      ...BASE_ORDER,
      status: "CONFIRMED",
      cancellation_requests: [{ id: 1, order_id: 7, status: "PENDING", reason: "x", created_at: "x" }],
      refunds: [],
    });

    await mainButtonHandler!();

    expect(mockRequestCancellation).toHaveBeenCalledWith(7, "wrong color, want to return it");
  });

  it("shows the pending cancellation-request status instead of a button once one exists", async () => {
    mockGetOrder.mockResolvedValue({
      ...BASE_ORDER,
      status: "CONFIRMED",
      cancellation_requests: [{ id: 1, order_id: 7, status: "PENDING", reason: "x", created_at: "x" }],
      refunds: [],
    });
    const container = document.createElement("div");
    await render(container, { id: "7" });

    expect(container.textContent).toContain("Bekor qilish so'rovi ko'rib chiqilmoqda");
  });

  it("shows a completed refund's amount and status", async () => {
    mockGetOrder.mockResolvedValue({
      ...BASE_ORDER,
      status: "CANCELLED",
      cancellation_requests: [],
      refunds: [{ id: 1, order_id: 7, amount: 100000, method: "CASH", status: "COMPLETED", created_at: "x" }],
    });
    const container = document.createElement("div");
    await render(container, { id: "7" });

    expect(container.textContent).toContain("Qaytarildi");
  });
});
