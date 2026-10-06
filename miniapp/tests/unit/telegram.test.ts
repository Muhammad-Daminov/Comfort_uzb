import { describe, it, expect, beforeEach, vi } from "vitest";

function makeButton() {
  return {
    show: vi.fn(),
    hide: vi.fn(),
    enable: vi.fn(),
    setText: vi.fn(),
    onClick: vi.fn(),
    offClick: vi.fn(),
  };
}

function installFakeWebApp() {
  const backButton = makeButton();
  const mainButton = makeButton();
  (window as unknown as { Telegram: unknown }).Telegram = {
    WebApp: {
      initData: "",
      themeParams: {},
      colorScheme: "light",
      ready: vi.fn(),
      expand: vi.fn(),
      onEvent: vi.fn(),
      offEvent: vi.fn(),
      MainButton: mainButton,
      BackButton: backButton,
    },
  };
  return { backButton, mainButton };
}

describe("telegram BackButton/MainButton handler lifecycle", () => {
  beforeEach(() => {
    vi.resetModules();
    delete (window as unknown as { Telegram?: unknown }).Telegram;
  });

  it("removes the previous BackButton handler before registering a new one across screen renders", async () => {
    const { backButton } = installFakeWebApp();
    const { setBackButton } = await import("../../src/telegram");

    const firstHandler = () => {};
    setBackButton(firstHandler);
    expect(backButton.onClick).toHaveBeenCalledWith(firstHandler);
    expect(backButton.offClick).not.toHaveBeenCalled();

    const secondHandler = () => {};
    setBackButton(secondHandler);

    expect(backButton.offClick).toHaveBeenCalledWith(firstHandler);
    expect(backButton.onClick).toHaveBeenCalledWith(secondHandler);
    expect(backButton.offClick).toHaveBeenCalledTimes(1);
  });

  it("removes the previous MainButton handler before registering a new one across screen renders", async () => {
    const { mainButton } = installFakeWebApp();
    const { setMainButton } = await import("../../src/telegram");

    const firstHandler = () => {};
    setMainButton("Birinchi", firstHandler);
    expect(mainButton.onClick).toHaveBeenCalledWith(firstHandler);

    const secondHandler = () => {};
    setMainButton("Ikkinchi", secondHandler);

    expect(mainButton.offClick).toHaveBeenCalledWith(firstHandler);
    expect(mainButton.onClick).toHaveBeenCalledWith(secondHandler);
    expect(mainButton.offClick).toHaveBeenCalledTimes(1);
  });

  it("the returned disposer removes its own handler and clears tracking", async () => {
    const { backButton } = installFakeWebApp();
    const { setBackButton } = await import("../../src/telegram");

    const handler = () => {};
    const dispose = setBackButton(handler);
    dispose();

    expect(backButton.offClick).toHaveBeenCalledWith(handler);
    expect(backButton.hide).toHaveBeenCalled();

    const nextHandler = () => {};
    setBackButton(nextHandler);
    // Tracking was cleared by dispose(), so no stale offClick for `handler` again.
    expect(backButton.offClick).toHaveBeenCalledTimes(1);
  });
});
