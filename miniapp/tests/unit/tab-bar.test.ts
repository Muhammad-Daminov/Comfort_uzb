import { describe, it, expect, beforeEach, vi } from "vitest";

vi.mock("../../src/router", () => ({ navigate: vi.fn() }));

import { tabsForRole, activeTabPath, mountTabBar } from "../../src/components/tab-bar";
import { setSession, clearSession } from "../../src/state/session";

describe("tabsForRole", () => {
  it("gives a plain user four tabs and no admin or owner entry", () => {
    const labels = tabsForRole(false, false).map((t) => t.label);
    expect(labels).toEqual(["Asosiy", "Savat", "Buyurtmalar", "Profil"]);
  });

  it("adds Admin panel for an admin but never Boshqaruv", () => {
    const labels = tabsForRole(true, false).map((t) => t.label);
    expect(labels).toEqual(["Asosiy", "Savat", "Buyurtmalar", "Profil", "Admin panel"]);
  });

  it("adds both Admin panel and Boshqaruv for an owner, with Profil before them", () => {
    const labels = tabsForRole(true, true).map((t) => t.label);
    expect(labels).toEqual(["Asosiy", "Savat", "Buyurtmalar", "Profil", "Admin panel", "Boshqaruv"]);
  });
});

describe("activeTabPath", () => {
  const tabs = tabsForRole(true, true);

  it.each([
    ["/home", "/home"],
    ["/catalog", "/home"],
    ["/product/12", "/home"],
    ["/cart", "/cart"],
    ["/checkout", "/cart"],
    ["/orders", "/orders"],
    ["/order/5", "/orders"],
    ["/payment/3", "/orders"],
    ["/receipt/9", "/orders"],
    ["/admin", "/admin"],
    ["/admin/product/3", "/admin"],
    ["/owner/finance", "/owner"],
    ["/profile", "/profile"],
  ])("marks %s as the %s tab", (path, expected) => {
    expect(activeTabPath(tabs, path)).toBe(expected);
  });

  /** Katalogni ko'rish endi "Asosiy" ekranining bir qismi — alohida tab
   *  emas, shu sabab hech qaysi tabga tegishli emas. */
  it("marks no tab for a screen outside the tab structure", () => {
    expect(activeTabPath(tabs, "/search")).toBeNull();
  });
});

describe("mountTabBar", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
    document.body.className = "";
    clearSession();
    window.location.hash = "";
  });

  it("renders an icon and a visible label for every tab", () => {
    setSession("t", 1, "USER");
    const nav = mountTabBar();
    const tabs = nav.querySelectorAll(".tab");
    expect(tabs).toHaveLength(4);
    for (const tab of tabs) {
      // Icons are inline SVG (no emoji/text glyph — src/components/icons.ts),
      // so an icon renders as an <svg> with no textContent by design.
      expect(tab.querySelector(".tab-icon svg")).toBeTruthy();
      expect(tab.querySelector(".tab-label")?.textContent).toBeTruthy();
    }
  });

  it("hides the Admin tab from a plain user and shows it to an admin", () => {
    setSession("t", 1, "USER");
    expect(mountTabBar().textContent).not.toContain("Admin");

    document.body.innerHTML = "";
    setSession("t", 1, "ADMIN");
    expect(mountTabBar().textContent).toContain("Admin");
  });

  it("hides the Owner tab from a plain admin", () => {
    setSession("t", 1, "ADMIN");
    const text = mountTabBar().textContent ?? "";
    expect(text).toContain("Admin");
    expect(text).not.toContain("Owner");
  });

  it("marks exactly one tab as current and follows hash changes", () => {
    setSession("t", 1, "OWNER");
    window.location.hash = "#/cart";
    const nav = mountTabBar();
    expect(nav.querySelectorAll('[aria-current="page"]')).toHaveLength(1);
    expect(nav.querySelector('[aria-current="page"]')?.textContent).toContain("Savat");

    window.location.hash = "#/owner/audit";
    window.dispatchEvent(new HashChangeEvent("hashchange"));
    expect(nav.querySelector('[aria-current="page"]')?.textContent).toContain("Boshqaruv");
  });

  /** Panel `#app` dan tashqarida bo'lishi shart: router har navigatsiyada
   *  `#app` ichini butunlay tozalaydi. */
  it("mounts outside #app and reserves room for itself", () => {
    const app = document.createElement("div");
    app.id = "app";
    document.body.appendChild(app);
    setSession("t", 1, "USER");
    const nav = mountTabBar();
    expect(app.contains(nav)).toBe(false);
    expect(document.body.classList.contains("has-tabbar")).toBe(true);
  });

  it("replaces a previously mounted bar instead of stacking a second one", () => {
    setSession("t", 1, "USER");
    mountTabBar();
    mountTabBar();
    expect(document.querySelectorAll(".tabbar")).toHaveLength(1);
  });
});
