import { describe, it, expect, beforeEach, vi } from "vitest";

/**
 * The router keeps its route table in module scope, so each case reloads the
 * module to start from an empty table.
 */
async function freshRouter() {
  vi.resetModules();
  return import("../../src/router");
}

function setHash(hash: string): void {
  window.location.hash = hash;
}

describe("router hash handling", () => {
  beforeEach(() => {
    setHash("");
  });

  it("renders the default screen when no route is requested", async () => {
    const router = await freshRouter();
    const home = vi.fn();
    const notFound = vi.fn();
    router.registerRoute("/home", home);
    router.registerNotFound(notFound);

    router.startRouter(document.createElement("div"));
    await Promise.resolve();

    expect(home).toHaveBeenCalledTimes(1);
    expect(notFound).not.toHaveBeenCalled();
  });

  /**
   * Regression: Telegram appends `#tgWebAppData=...` when it opens a Mini App
   * and never strips it, so every launch from inside Telegram used to be
   * matched as a route and fell through to "Sahifa topilmadi.".
   */
  it("ignores Telegram's launch fragment and still renders the default screen", async () => {
    const router = await freshRouter();
    const home = vi.fn();
    const notFound = vi.fn();
    router.registerRoute("/home", home);
    router.registerNotFound(notFound);

    setHash("#tgWebAppData=query_id%3DAAF%26user%3D%257B%2522id%2522%253A1%257D&tgWebAppVersion=7.0");
    router.startRouter(document.createElement("div"));
    await Promise.resolve();

    expect(home).toHaveBeenCalledTimes(1);
    expect(notFound).not.toHaveBeenCalled();
  });

  it("still routes normally once a real route is set", async () => {
    const router = await freshRouter();
    const home = vi.fn();
    const product = vi.fn();
    router.registerRoute("/home", home);
    router.registerRoute("/product/:id", product);

    setHash("#/product/42");
    router.startRouter(document.createElement("div"));
    await Promise.resolve();

    expect(product).toHaveBeenCalledTimes(1);
    expect(product.mock.calls[0][1]).toEqual({ id: "42" });
    expect(home).not.toHaveBeenCalled();
  });

  it("still shows not-found for an unknown route path", async () => {
    const router = await freshRouter();
    const notFound = vi.fn();
    router.registerRoute("/home", vi.fn());
    router.registerNotFound(notFound);

    setHash("#/nope");
    router.startRouter(document.createElement("div"));
    await Promise.resolve();

    expect(notFound).toHaveBeenCalledTimes(1);
  });
});
