import { describe, it, expect, vi, beforeEach } from "vitest";

const mockListAuditLogs = vi.fn();
vi.mock("../../src/api/owner", () => ({
  listAuditLogs: (...args: unknown[]) => mockListAuditLogs(...args),
}));
vi.mock("../../src/telegram", () => ({
  setMainButtonBusy: vi.fn(),
  resetMainButton: vi.fn(), setBackButton: vi.fn(() => () => {}) }));
vi.mock("../../src/state/session", () => ({ isOwnerRole: () => true }));

import { render } from "../../src/screens/owner/audit";

beforeEach(() => {
  mockListAuditLogs.mockReset();
});

const ENTRY = {
  id: 1,
  actor_id: 5,
  actor_role: "OWNER",
  action: "admin.create",
  entity_type: "user",
  entity_id: 42,
  old_data: null,
  new_data: { telegram_id: 123 },
  created_at: "2026-08-01T00:00:00Z",
};

describe("owner audit log screen", () => {
  it("renders audit entries from real backend data", async () => {
    mockListAuditLogs.mockResolvedValue({ items: [ENTRY], next_cursor: null });
    const container = document.createElement("div");

    await render(container);

    expect(mockListAuditLogs).toHaveBeenCalledWith(undefined);
    expect(container.textContent).toContain("admin.create");
    expect(container.textContent).toContain("user#42");
    expect(container.textContent).toContain("actor #5");
  });

  it("shows an empty state when there are no audit entries", async () => {
    mockListAuditLogs.mockResolvedValue({ items: [], next_cursor: null });
    const container = document.createElement("div");

    await render(container);

    expect(container.textContent).toContain("Audit yozuvlari yo'q.");
  });

  it("shows a load-more button when a next cursor is returned, and paginates on click", async () => {
    mockListAuditLogs.mockResolvedValueOnce({ items: [ENTRY], next_cursor: "abc123" });
    const container = document.createElement("div");

    await render(container);

    const loadMoreButton = Array.from(container.querySelectorAll("button")).find((b) => b.textContent === "Ko'proq");
    expect(loadMoreButton?.style.display).not.toBe("none");

    mockListAuditLogs.mockResolvedValueOnce({ items: [{ ...ENTRY, id: 2 }], next_cursor: null });
    loadMoreButton?.click();
    await Promise.resolve();
    await Promise.resolve();

    expect(mockListAuditLogs).toHaveBeenLastCalledWith("abc123");
    expect(loadMoreButton?.style.display).toBe("none");
  });

  it("shows a retry button on failure", async () => {
    mockListAuditLogs.mockRejectedValue(new Error("boom"));
    const container = document.createElement("div");

    await render(container);

    const retryButton = Array.from(container.querySelectorAll("button")).find((b) => b.textContent?.includes("urinib"));
    expect(retryButton).toBeTruthy();
  });
});
