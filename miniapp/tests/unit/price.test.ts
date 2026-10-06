import { describe, it, expect } from "vitest";
import { formatSom } from "../../src/components/price";

describe("formatSom", () => {
  it("formats a whole-number amount with a space thousands separator", () => {
    expect(formatSom(850000)).toBe("850 000 so'm");
  });

  it("formats small amounts without separators", () => {
    expect(formatSom(500)).toBe("500 so'm");
  });

  it("formats zero", () => {
    expect(formatSom(0)).toBe("0 so'm");
  });
});
