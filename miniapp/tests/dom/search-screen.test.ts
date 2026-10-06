import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

const mockSearchProducts = vi.fn();
vi.mock("../../src/api/catalog", () => ({
  searchProducts: (...args: unknown[]) => mockSearchProducts(...args),
}));
vi.mock("../../src/telegram", () => ({
  setMainButtonBusy: vi.fn(),
  resetMainButton: vi.fn(),
  setBackButton: vi.fn(() => () => {}),
}));

import { render } from "../../src/screens/search";

beforeEach(() => {
  mockSearchProducts.mockReset();
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

function typeInto(input: HTMLInputElement, value: string): void {
  input.value = value;
  input.dispatchEvent(new Event("input"));
}

describe("search screen", () => {
  it("debounces input and issues exactly one request per settled query", async () => {
    mockSearchProducts.mockResolvedValue({ items: [] });
    const container = document.createElement("div");
    render(container);
    const input = container.querySelector("input") as HTMLInputElement;

    typeInto(input, "n");
    typeInto(input, "ne");
    typeInto(input, "nex");
    await vi.advanceTimersByTimeAsync(300);

    expect(mockSearchProducts).toHaveBeenCalledTimes(1);
    expect(mockSearchProducts).toHaveBeenCalledWith("nex", expect.anything());
  });

  it("shows an empty state for zero results", async () => {
    mockSearchProducts.mockResolvedValue({ items: [] });
    const container = document.createElement("div");
    render(container);
    const input = container.querySelector("input") as HTMLInputElement;

    typeInto(input, "nothing-matches");
    await vi.advanceTimersByTimeAsync(300);
    await vi.waitFor(() => expect(container.textContent).toContain("Hech narsa topilmadi"));
  });

  it("clears results when the query is emptied", async () => {
    mockSearchProducts.mockResolvedValue({ items: [{ id: 1, name: "X", brand_id: 1, status: "ACTIVE", created_at: "", min_price: 1, total_available: 1, popularity: 0 }] });
    const container = document.createElement("div");
    render(container);
    const input = container.querySelector("input") as HTMLInputElement;

    typeInto(input, "x");
    await vi.advanceTimersByTimeAsync(300);
    await vi.waitFor(() => expect(container.textContent).toContain("X"));

    typeInto(input, "");
    expect(mockSearchProducts).toHaveBeenCalledTimes(1); // no new request just for clearing
  });
});
