import { describe, it, expect, vi, beforeEach } from "vitest";

const mockAdminListPayments = vi.fn();
const mockAdminReviewPayment = vi.fn();
const mockAdminGetReceiptUrl = vi.fn();
vi.mock("../../src/api/admin", () => ({
  adminListPayments: (...args: unknown[]) => mockAdminListPayments(...args),
  adminReviewPayment: (...args: unknown[]) => mockAdminReviewPayment(...args),
  adminGetReceiptUrl: (...args: unknown[]) => mockAdminGetReceiptUrl(...args),
}));
vi.mock("../../src/telegram", () => ({
  setMainButtonBusy: vi.fn(),
  resetMainButton: vi.fn(),
  setBackButton: vi.fn(() => () => {}),
}));

import { render } from "../../src/screens/admin/payments";

beforeEach(() => {
  mockAdminListPayments.mockReset();
  mockAdminReviewPayment.mockReset();
  mockAdminGetReceiptUrl.mockReset();
});

const SAMPLE_PAYMENT = { id: 7, order_id: 42, amount: 150000, method: "CARD", status: "PENDING" };

describe("admin payments screen", () => {
  it("shows an empty state when there are no pending payments", async () => {
    mockAdminListPayments.mockResolvedValue({ items: [] });
    const container = document.createElement("div");

    await render(container);

    expect(mockAdminListPayments).toHaveBeenCalledWith("PENDING");
    expect(container.textContent).toContain("Kutilayotgan to'lovlar yo'q");
  });

  it("renders a pending payment with its amount and order reference", async () => {
    mockAdminListPayments.mockResolvedValue({ items: [SAMPLE_PAYMENT] });
    const container = document.createElement("div");

    await render(container);

    expect(container.textContent).toContain("To'lov #7");
    expect(container.textContent).toContain("Buyurtma #42");
    expect(container.textContent).toContain("150 000 so'm");
  });

  it("approves a payment and reloads the list", async () => {
    mockAdminListPayments.mockResolvedValue({ items: [SAMPLE_PAYMENT] });
    mockAdminReviewPayment.mockResolvedValue({ ...SAMPLE_PAYMENT, status: "APPROVED" });
    const container = document.createElement("div");
    await render(container);

    const approveButton = Array.from(container.querySelectorAll("button")).find(
      (b) => b.textContent === "Tasdiqlash",
    )!;
    approveButton.click();
    await new Promise((r) => setTimeout(r, 0));

    expect(mockAdminReviewPayment).toHaveBeenCalledWith(7, true);
    expect(mockAdminListPayments).toHaveBeenCalledTimes(2); // initial + reload after approve
  });

  it("rejects a payment only after a reason is provided", async () => {
    mockAdminListPayments.mockResolvedValue({ items: [SAMPLE_PAYMENT] });
    const promptSpy = vi.spyOn(window, "prompt").mockReturnValue(null);
    const container = document.createElement("div");
    await render(container);

    const rejectButton = Array.from(container.querySelectorAll("button")).find((b) => b.textContent === "Rad etish")!;
    rejectButton.click();
    await new Promise((r) => setTimeout(r, 0));

    expect(mockAdminReviewPayment).not.toHaveBeenCalled();
    promptSpy.mockRestore();
  });
});
