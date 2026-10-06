import { describe, it, expect, vi, beforeEach } from "vitest";

const mockListAdmins = vi.fn();
const mockCreateAdmin = vi.fn();
const mockDeactivateAdmin = vi.fn();
vi.mock("../../src/api/owner", () => ({
  listAdmins: (...args: unknown[]) => mockListAdmins(...args),
  createAdmin: (...args: unknown[]) => mockCreateAdmin(...args),
  deactivateAdmin: (...args: unknown[]) => mockDeactivateAdmin(...args),
  reactivateAdmin: vi.fn(),
}));
vi.mock("../../src/telegram", () => ({
  setMainButtonBusy: vi.fn(),
  resetMainButton: vi.fn(), setBackButton: vi.fn(() => () => {}) }));

import { render } from "../../src/screens/owner/admins";

beforeEach(() => {
  mockListAdmins.mockReset();
  mockCreateAdmin.mockReset();
  mockDeactivateAdmin.mockReset();
});

describe("owner admins screen", () => {
  it("shows an empty state with no admins", async () => {
    mockListAdmins.mockResolvedValue({ items: [] });
    const container = document.createElement("div");

    await render(container);

    expect(container.textContent).toContain("Administratorlar yo'q");
  });

  it("rejects create with no telegram id, never calling the backend", async () => {
    mockListAdmins.mockResolvedValue({ items: [] });
    const container = document.createElement("div");
    await render(container);

    const createButton = Array.from(container.querySelectorAll("button")).find((b) => b.textContent?.includes("qo'shish"))!;
    createButton.click();
    await new Promise((r) => setTimeout(r, 0));

    expect(mockCreateAdmin).not.toHaveBeenCalled();
  });

  it("creates an admin and reloads the list on valid input", async () => {
    mockListAdmins.mockResolvedValue({ items: [] });
    mockCreateAdmin.mockResolvedValue({ id: 1, telegram_id: 555 });
    const container = document.createElement("div");
    await render(container);

    const telegramIdInput = container.querySelector("input[type=number]") as HTMLInputElement;
    telegramIdInput.value = "555";

    const createButton = Array.from(container.querySelectorAll("button")).find((b) => b.textContent?.includes("qo'shish"))!;
    createButton.click();
    await new Promise((r) => setTimeout(r, 0));

    expect(mockCreateAdmin).toHaveBeenCalledWith(555, undefined);
    expect(mockListAdmins).toHaveBeenCalledTimes(2); // initial + reload after create
  });

  it("renders an active admin with a deactivate action", async () => {
    mockListAdmins.mockResolvedValue({
      items: [{ id: 1, telegram_id: 555, first_name: "Ali", last_name: null, username: null, status: "ACTIVE", created_at: "" }],
    });
    const container = document.createElement("div");

    await render(container);

    expect(container.textContent).toContain("Ali");
    expect(container.textContent).toContain("Faolsizlantirish");
  });
});
