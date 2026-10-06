import { describe, it, expect, vi, beforeEach } from "vitest";

const mockGetSettings = vi.fn();
const mockPutSettings = vi.fn();
vi.mock("../../src/api/owner", () => ({
  getSettings: (...args: unknown[]) => mockGetSettings(...args),
  putSettings: (...args: unknown[]) => mockPutSettings(...args),
}));
vi.mock("../../src/telegram", () => ({
  setMainButtonBusy: vi.fn(),
  resetMainButton: vi.fn(), setBackButton: vi.fn(() => () => {}) }));

import { render } from "../../src/screens/owner/settings";

beforeEach(() => {
  mockGetSettings.mockReset();
  mockPutSettings.mockReset();
});

describe("owner settings screen", () => {
  it("shows an empty state when no settings exist yet (Phase 07's zero-invented-content decision)", async () => {
    mockGetSettings.mockResolvedValue({});
    const container = document.createElement("div");

    await render(container);

    expect(container.textContent).toContain("hali kiritilmagan");
  });

  it("renders existing key/value settings", async () => {
    mockGetSettings.mockResolvedValue({ store_name: "Comfort UZB" });
    const container = document.createElement("div");

    await render(container);

    expect(container.textContent).toContain("store_name");
    expect(container.textContent).toContain("Comfort UZB");
  });

  it("rejects saving with an empty key, never calling the backend", async () => {
    mockGetSettings.mockResolvedValue({});
    const container = document.createElement("div");
    await render(container);

    const saveButton = Array.from(container.querySelectorAll("button")).find((b) => b.textContent === "Saqlash")!;
    saveButton.click();
    await new Promise((r) => setTimeout(r, 0));

    expect(mockPutSettings).not.toHaveBeenCalled();
  });

  it("saves a key/value pair and reloads", async () => {
    mockGetSettings.mockResolvedValue({});
    mockPutSettings.mockResolvedValue({ store_name: "New" });
    const container = document.createElement("div");
    await render(container);

    const inputs = container.querySelectorAll("input");
    (inputs[0] as HTMLInputElement).value = "store_name";
    (inputs[1] as HTMLInputElement).value = "New";

    const saveButton = Array.from(container.querySelectorAll("button")).find((b) => b.textContent === "Saqlash")!;
    saveButton.click();
    await new Promise((r) => setTimeout(r, 0));

    expect(mockPutSettings).toHaveBeenCalledWith({ store_name: "New" });
  });
});
