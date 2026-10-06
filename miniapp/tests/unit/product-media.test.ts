import { describe, it, expect } from "vitest";
import { productMedia, productPlaceholder, initialOf } from "../../src/components/product-media";

describe("initialOf", () => {
  it("takes the first letter and uppercases it", () => {
    expect(initialOf("teri sidena to'plami")).toBe("T");
    expect(initialOf("  alkantara")).toBe("A");
  });

  it("skips leading punctuation and emoji rather than showing them", () => {
    expect(initialOf("«Sport» sidena")).toBe("S");
    expect(initialOf("🪑 sidena")).toBe("S");
  });

  it("returns nothing for a nameless product instead of a stray '?'", () => {
    expect(initialOf("")).toBe("");
    expect(initialOf("—")).toBe("");
  });
});

describe("productPlaceholder", () => {
  it("draws a seat silhouette and the initial, not a flat colour block", () => {
    const box = productPlaceholder("Teri sidena");
    expect(box.querySelector("svg.pm-icon")).not.toBeNull();
    expect(box.querySelector(".pm-letter")?.textContent).toBe("T");
  });

  it("announces itself to a screen reader as a missing image", () => {
    const box = productPlaceholder("Teri sidena");
    expect(box.getAttribute("role")).toBe("img");
    expect(box.getAttribute("aria-label")).toContain("Teri sidena");
  });
});

describe("productMedia", () => {
  it("shows the placeholder when there is no image", () => {
    const box = productMedia(null, "Sport sidena");
    expect(box.querySelector("img")).toBeNull();
    expect(box.querySelector(".pm-empty")).not.toBeNull();
  });

  it("shows the image when there is one, lazily", () => {
    const box = productMedia("/files/products/1/a.webp?md5=x", "Sport sidena");
    const img = box.querySelector("img");
    expect(img?.getAttribute("src")).toContain("/files/products/1/a.webp");
    expect(img?.getAttribute("alt")).toBe("Sport sidena");
    expect(img?.getAttribute("loading")).toBe("lazy");
  });

  /** Imzo muddati o'tgan bo'lsa <img> oddiy yuklash xatosi beradi (ADR-13) —
   *  foydalanuvchi buzilgan rasm belgisini emas, o'rin bosuvchini ko'radi. */
  it("falls back to the placeholder when the signed URL fails to load", () => {
    const box = productMedia("/files/expired.webp", "Sport sidena");
    box.querySelector("img")!.dispatchEvent(new Event("error"));
    expect(box.querySelector("img")).toBeNull();
    expect(box.querySelector(".pm-empty")).not.toBeNull();
  });

  it.each([
    ["sm", "pm-56"],
    ["md", "pm-72"],
    ["full", "pm-full"],
  ] as const)("applies the %s size class", (size, expected) => {
    expect(productMedia(null, "x", { size }).className).toContain(expected);
  });
});
