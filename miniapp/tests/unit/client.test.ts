import { describe, it, expect, vi, afterEach } from "vitest";
import { apiRequest, ApiError } from "../../src/api/client";
import * as session from "../../src/state/session";

afterEach(() => {
  vi.restoreAllMocks();
  session.clearSession();
});

describe("apiRequest error mapping", () => {
  it.each([
    [401, "unauthorized"],
    [403, "forbidden"],
    [404, "not_found"],
    [409, "conflict"],
    [422, "validation"],
    [500, "server_error"],
  ] as const)("maps HTTP %i to kind %s", async (status, expectedKind) => {
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ error: { code: "X", message: "boom" } }), { status }),
    );

    await expect(apiRequest("/whatever")).rejects.toMatchObject({ kind: expectedKind, code: "X" });
  });

  it("maps a thrown fetch (network failure) to kind network", async () => {
    globalThis.fetch = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));

    await expect(apiRequest("/whatever")).rejects.toMatchObject({ kind: "network" });
  });

  it("returns parsed JSON on success", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }));

    const result = await apiRequest<{ ok: boolean }>("/whatever");
    expect(result.ok).toBe(true);
  });

  it("attaches the Authorization header when a session token is set", async () => {
    session.setSession("test-token", 1, "USER");
    const fetchMock = vi.fn().mockResolvedValue(new Response("{}", { status: 200 }));
    globalThis.fetch = fetchMock;

    await apiRequest("/whatever");

    const [, init] = fetchMock.mock.calls[0];
    expect((init.headers as Record<string, string>)["Authorization"]).toBe("Bearer test-token");
  });

  it("attaches Idempotency-Key when provided", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("{}", { status: 200 }));
    globalThis.fetch = fetchMock;

    await apiRequest("/orders", { method: "POST", body: {}, idempotencyKey: "abc-123" });

    const [, init] = fetchMock.mock.calls[0];
    expect((init.headers as Record<string, string>)["Idempotency-Key"]).toBe("abc-123");
  });

  it("propagates AbortError distinctly from a network ApiError", async () => {
    const abortError = new DOMException("aborted", "AbortError");
    globalThis.fetch = vi.fn().mockRejectedValue(abortError);

    await expect(apiRequest("/whatever")).rejects.toBe(abortError);
  });
});

describe("ApiError", () => {
  it("is an instance of Error", () => {
    const err = new ApiError("server_error", "boom", 500, null, null);
    expect(err).toBeInstanceOf(Error);
    expect(err.message).toBe("boom");
  });
});
