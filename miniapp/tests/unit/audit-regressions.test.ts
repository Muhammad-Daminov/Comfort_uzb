/**
 * Regression tests for the Mini App defects found by the full-system audit
 * (docs/11_FULL_SYSTEM_AUDIT_REPORT.md, F-ids). Each case fails on the
 * pre-fix code.
 */
import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { apiRequest, extractErrorEnvelope } from "../../src/api/client";
import { uuid } from "../../src/uuid";
import { exclusiveEnd } from "../../src/api/owner";
import { signedImage } from "../../src/components/signed-image";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("F1/H3 — error envelope parsing against the shapes the backend actually sends", () => {
  it("reads the §13.5 top-level envelope", () => {
    expect(extractErrorEnvelope({ error: { code: "PRICE_MISMATCH", message: "m", details: { x: 1 } } })).toEqual({
      code: "PRICE_MISMATCH",
      message: "m",
      details: { x: 1 },
    });
  });

  it("reads an envelope nested under FastAPI's `detail` (pre-fix backend / replayed idempotent 4xx)", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: { error: { code: "INSUFFICIENT_STOCK", message: "2 ta qoldi" } } }), { status: 409 }),
    );
    await expect(apiRequest("/orders")).rejects.toMatchObject({ code: "INSUFFICIENT_STOCK", message: "2 ta qoldi", kind: "conflict" });
  });

  it("uses a plain string `detail` as the message", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "missing bearer token" }), { status: 401 }));
    await expect(apiRequest("/cart")).rejects.toMatchObject({ code: null, message: "missing bearer token" });
  });

  it("prefers the top-level envelope when both are present (current backend)", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: "x", error: { code: "FORBIDDEN", message: "Permission denied" } }), { status: 403 }),
    );
    await expect(apiRequest("/admin/orders")).rejects.toMatchObject({ code: "FORBIDDEN", message: "Permission denied" });
  });
});

describe("F7 — uuid() works without crypto.randomUUID", () => {
  it("falls back to getRandomValues and still produces RFC 4122 v4", () => {
    vi.stubGlobal("crypto", { getRandomValues: (b: Uint8Array) => { for (let i = 0; i < b.length; i++) b[i] = i * 17; return b; } });
    const id = uuid();
    expect(id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  });

  it("uses crypto.randomUUID when available", () => {
    vi.stubGlobal("crypto", { randomUUID: () => "11111111-2222-4333-8444-555555555555" });
    expect(uuid()).toBe("11111111-2222-4333-8444-555555555555");
  });
});

describe("F12/M7 — owner date range is inclusive of the `to` day", () => {
  it("sends the day after `to` to the backend's half-open range", () => {
    expect(exclusiveEnd("2026-09-18")).toBe("2026-09-19");
    expect(exclusiveEnd("2026-12-31")).toBe("2027-01-01");
    expect(exclusiveEnd("garbage")).toBe("garbage");
  });
});

describe("F5 — a broken signed image refetches at most once", () => {
  it("calls onExpired once, then degrades to a placeholder instead of looping", () => {
    const onExpired = vi.fn();
    const url = `/files/products/1/${Math.random()}.webp?s=x&e=1`;
    const first = signedImage(url, "alt", onExpired) as HTMLImageElement;
    first.dispatchEvent(new Event("error"));
    expect(onExpired).toHaveBeenCalledTimes(1);

    // the re-render mounts a fresh <img> with the same (still broken) URL
    const parent = document.createElement("div");
    const second = signedImage(url, "alt", onExpired) as HTMLImageElement;
    parent.appendChild(second);
    second.dispatchEvent(new Event("error"));
    expect(onExpired).toHaveBeenCalledTimes(1);
    expect(parent.querySelector("img")).toBeNull();
    expect(parent.querySelector(".signed-img-placeholder")).not.toBeNull();
  });
});

describe("F3/F4 — router isolates screens from each other", () => {
  beforeEach(() => {
    window.location.hash = "";
    vi.resetModules();
  });

  it("gives every navigation a fresh mount so a slow, abandoned screen cannot clobber the new one", async () => {
    const resetMainButton = vi.fn();
    vi.doMock("../../src/telegram", () => ({ resetMainButton }));
    const router = await import("../../src/router");

    let releaseSlow: (() => void) | null = null;
    const slow = vi.fn(async (container: HTMLElement) => {
      await new Promise<void>((resolve) => { releaseSlow = resolve; });
      container.innerHTML = ""; // what product-detail/order-detail do after their fetch resolves
      container.textContent = "SLOW SCREEN";
    });
    const fast = vi.fn((container: HTMLElement) => { container.textContent = "FAST SCREEN"; });
    router.registerRoute("/slow", slow);
    router.registerRoute("/fast", fast);

    const mount = document.createElement("div");
    window.location.hash = "#/slow";
    router.startRouter(mount);
    await Promise.resolve();
    expect(slow).toHaveBeenCalledTimes(1);

    window.location.hash = "#/fast";
    window.dispatchEvent(new HashChangeEvent("hashchange"));
    await new Promise((r) => setTimeout(r, 0));
    expect(mount.textContent).toBe("FAST SCREEN");

    releaseSlow!();
    await new Promise((r) => setTimeout(r, 0));
    expect(mount.textContent).toBe("FAST SCREEN"); // the late write landed on a detached node
    expect(resetMainButton.mock.calls.length).toBeGreaterThanOrEqual(2); // at least once per navigation
    vi.doUnmock("../../src/telegram");
  });
});

describe("F3 — resetMainButton detaches the previous screen's handler", () => {
  it("offClicks the last handler and hides the button", async () => {
    vi.doUnmock("../../src/telegram");
    vi.resetModules();
    const mainButton = { show: vi.fn(), hide: vi.fn(), enable: vi.fn(), disable: vi.fn(), setText: vi.fn(), onClick: vi.fn(), offClick: vi.fn(), showProgress: vi.fn(), hideProgress: vi.fn() };
    (window as unknown as { Telegram: unknown }).Telegram = {
      WebApp: { initData: "", themeParams: {}, colorScheme: "light", ready: vi.fn(), expand: vi.fn(), onEvent: vi.fn(), offEvent: vi.fn(), MainButton: mainButton, BackButton: { ...mainButton } },
    };
    const telegram = await import("../../src/telegram");
    const handler = vi.fn();
    telegram.setMainButton("Savatga qo'shish", handler);
    telegram.resetMainButton();
    expect(mainButton.offClick).toHaveBeenCalledWith(handler);
    expect(mainButton.hide).toHaveBeenCalled();
    telegram.setMainButtonBusy(true);
    expect(mainButton.showProgress).toHaveBeenCalled();
    expect(mainButton.disable).toHaveBeenCalled();
    telegram.setMainButtonBusy(false);
    expect(mainButton.hideProgress).toHaveBeenCalled();
    expect(mainButton.enable).toHaveBeenCalled();
    delete (window as unknown as { Telegram?: unknown }).Telegram;
  });
});
