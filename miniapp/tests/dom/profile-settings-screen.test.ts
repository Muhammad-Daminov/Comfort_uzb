import { describe, it, expect, vi, beforeEach } from "vitest";

const mockGetMe = vi.fn();
const mockUpdateNotificationSettings = vi.fn();
vi.mock("../../src/api/auth", () => ({
  getMe: (...args: unknown[]) => mockGetMe(...args),
  updateNotificationSettings: (...args: unknown[]) => mockUpdateNotificationSettings(...args),
}));
vi.mock("../../src/telegram", () => ({
  setBackButton: vi.fn(() => () => {}),
  hideMainButton: vi.fn(),
}));

import { render } from "../../src/screens/profile-settings";

const SAMPLE_ME = {
  id: 1,
  telegram_id: 555,
  first_name: "Dilnoza",
  last_name: null,
  username: "dilnoza",
  role: "USER",
  phone: "+998901234567",
  status: "ACTIVE",
  telegram_notifications_enabled: true,
};

beforeEach(() => {
  mockGetMe.mockReset();
  mockUpdateNotificationSettings.mockReset();
});

describe("profile settings screen", () => {
  it("renders name and phone from real backend data", async () => {
    mockGetMe.mockResolvedValue(SAMPLE_ME);
    const container = document.createElement("div");

    await render(container);

    expect(container.textContent).toContain("Dilnoza");
    expect(container.textContent).toContain("+998901234567");
  });

  it("shows the single supported language as a display-only value, not an editable switcher", async () => {
    mockGetMe.mockResolvedValue(SAMPLE_ME);
    const container = document.createElement("div");

    await render(container);

    expect(container.textContent).toContain("O'zbekcha");
    // No <select>/interactive control for language — nothing to switch to.
    expect(container.querySelector("select")).toBeNull();
  });

  it("shows the notification preference reflecting the backend's current value", async () => {
    mockGetMe.mockResolvedValue(SAMPLE_ME);
    const container = document.createElement("div");

    await render(container);

    const toggle = container.querySelector('[aria-pressed]') as HTMLButtonElement;
    expect(toggle.getAttribute("aria-pressed")).toBe("true");
    expect(toggle.textContent).toBe("Yoqilgan");
  });

  it("persists a preference change via the backend and reflects the new state", async () => {
    mockGetMe.mockResolvedValue(SAMPLE_ME);
    mockUpdateNotificationSettings.mockResolvedValue({ ...SAMPLE_ME, telegram_notifications_enabled: false });
    const container = document.createElement("div");
    await render(container);

    const toggle = container.querySelector('[aria-pressed]') as HTMLButtonElement;
    toggle.click();
    await Promise.resolve();
    await Promise.resolve();

    expect(mockUpdateNotificationSettings).toHaveBeenCalledWith(false);
    expect(toggle.getAttribute("aria-pressed")).toBe("false");
    expect(toggle.textContent).toBe("O'chirilgan");
  });

  it("shows a retry button on a profile load failure", async () => {
    mockGetMe.mockRejectedValue(new Error("boom"));
    const container = document.createElement("div");

    await render(container);

    const retryButton = Array.from(container.querySelectorAll("button")).find((b) =>
      b.textContent?.includes("urinib"),
    );
    expect(retryButton).toBeTruthy();
  });
});
