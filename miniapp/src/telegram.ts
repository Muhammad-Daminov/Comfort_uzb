/**
 * Thin wrapper around `window.Telegram.WebApp` — §14.2's Telegram
 * integration requirements (theme adaptation, safe-area, MainButton,
 * BackButton) in one place, so screens never touch the global directly.
 * Falls back gracefully outside Telegram (e.g. local dev in a plain
 * browser) instead of throwing.
 */

interface TelegramThemeParams {
  bg_color?: string;
  text_color?: string;
  hint_color?: string;
  link_color?: string;
  button_color?: string;
  button_text_color?: string;
  secondary_bg_color?: string;
  destructive_text_color?: string;
}

interface TelegramWebApp {
  initData: string;
  themeParams: TelegramThemeParams;
  colorScheme: "light" | "dark";
  ready(): void;
  expand(): void;
  close(): void;
  onEvent(event: string, handler: () => void): void;
  offEvent(event: string, handler: () => void): void;
  MainButton: {
    text: string;
    show(): void;
    hide(): void;
    enable(): void;
    disable(): void;
    onClick(handler: () => void): void;
    offClick(handler: () => void): void;
    setText(text: string): void;
    showProgress(leaveActive?: boolean): void;
    hideProgress(): void;
  };
  BackButton: {
    show(): void;
    hide(): void;
    onClick(handler: () => void): void;
    offClick(handler: () => void): void;
  };
  CloudStorage?: {
    setItem(key: string, value: string, cb?: (err: unknown, ok: boolean) => void): void;
    getItem(key: string, cb: (err: unknown, value: string) => void): void;
  };
}

declare global {
  interface Window {
    Telegram?: { WebApp: TelegramWebApp };
  }
}

function getWebApp(): TelegramWebApp | null {
  return window.Telegram?.WebApp ?? null;
}

export function initTelegram(): void {
  const webApp = getWebApp();
  if (!webApp) return;
  webApp.ready();
  webApp.expand();
  applyTheme(webApp.themeParams);
  applyColorScheme(webApp.colorScheme);
  webApp.onEvent("themeChanged", () => {
    applyTheme(webApp.themeParams);
    applyColorScheme(webApp.colorScheme);
  });
}

/** The brand accents are deliberately NOT taken from themeParams — they are
 *  the app's identity and must stay constant across every Telegram theme.
 *  They still need a dark variant, and Telegram's colorScheme is the only
 *  reliable signal for that (a user can run Telegram dark on a light OS, so
 *  prefers-color-scheme would be wrong). Stamped on <html> so theme.css can
 *  switch the accents; outside Telegram the attribute is absent and the
 *  stylesheet falls back to prefers-color-scheme. */
function applyColorScheme(scheme: "light" | "dark"): void {
  document.documentElement.setAttribute("data-theme", scheme);
}

function applyTheme(params: TelegramThemeParams): void {
  const root = document.documentElement;
  const map: Record<string, string | undefined> = {
    "--tg-bg-color": params.bg_color,
    "--tg-text-color": params.text_color,
    "--tg-hint-color": params.hint_color,
    "--tg-link-color": params.link_color,
    "--tg-button-color": params.button_color,
    "--tg-button-text-color": params.button_text_color,
    "--tg-secondary-bg-color": params.secondary_bg_color,
    "--tg-destructive-text-color": params.destructive_text_color,
  };
  for (const [cssVar, value] of Object.entries(map)) {
    if (value) root.style.setProperty(cssVar, `#${value.replace(/^#/, "")}`);
  }
}

/** §P2-1: the AI Assistant lives in the bot chat (text/voice/image), not
 *  as a Mini App screen — the Mini App was opened *from* that exact chat
 *  via the Menu Button, so closing it is the entire "deep link": Telegram
 *  returns the admin to the same chat, no bot username/deep-link URL
 *  needed (nothing hardcoded, no new backend endpoint). Outside Telegram
 *  (plain browser, local dev) there is nothing to close — a no-op. */
export function closeMiniApp(): void {
  getWebApp()?.close();
}

export function getInitData(): string {
  return getWebApp()?.initData ?? "";
}

// The real Telegram WebApp SDK's BackButton/MainButton .onClick() *adds* a
// listener rather than replacing the previous one — .offClick() with the
// same function reference is required to remove it. Screens call
// setBackButton/setMainButton fresh on every render with a brand-new
// closure and never invoke the returned disposer (the router doesn't
// track per-screen cleanup between navigations either), so without this
// bookkeeping, handlers from every previously visited screen would keep
// firing alongside the current one. Tracking (and removing) the single
// most-recently-registered handler here, rather than relying on callers,
// keeps at most one live handler per button regardless of navigation.
let lastMainHandler: (() => void) | null = null;
let lastBackHandler: (() => void) | null = null;

export function setMainButton(text: string, onClick: () => void): () => void {
  const webApp = getWebApp();
  if (!webApp) return () => {};
  if (lastMainHandler) webApp.MainButton.offClick(lastMainHandler);
  webApp.MainButton.setText(text);
  webApp.MainButton.show();
  webApp.MainButton.enable();
  webApp.MainButton.onClick(onClick);
  lastMainHandler = onClick;
  return () => {
    webApp.MainButton.offClick(onClick);
    if (lastMainHandler === onClick) lastMainHandler = null;
    webApp.MainButton.hide();
  };
}

export function hideMainButton(): void {
  getWebApp()?.MainButton.hide();
}

/**
 * Called by the router before every screen render. A screen that never
 * calls setMainButton (Home, Catalog, every admin/owner list) used to
 * inherit the previous screen's button — "Savatga qo'shish" stayed visible
 * on Home and still added the product when tapped.
 */
export function resetMainButton(): void {
  const webApp = getWebApp();
  if (!webApp) return;
  if (lastMainHandler) webApp.MainButton.offClick(lastMainHandler);
  lastMainHandler = null;
  webApp.MainButton.hideProgress();
  webApp.MainButton.hide();
}

/** Disables the button and shows the spinner while a mutation is in flight
 *  (double-tapping "Buyurtma berish" used to send two orders). */
export function setMainButtonBusy(busy: boolean): void {
  const webApp = getWebApp();
  if (!webApp) return;
  if (busy) {
    webApp.MainButton.showProgress();
    webApp.MainButton.disable();
  } else {
    webApp.MainButton.hideProgress();
    webApp.MainButton.enable();
  }
}

export function setBackButton(onClick: () => void): () => void {
  const webApp = getWebApp();
  if (!webApp) return () => {};
  if (lastBackHandler) webApp.BackButton.offClick(lastBackHandler);
  webApp.BackButton.show();
  webApp.BackButton.onClick(onClick);
  lastBackHandler = onClick;
  return () => {
    webApp.BackButton.offClick(onClick);
    if (lastBackHandler === onClick) lastBackHandler = null;
    webApp.BackButton.hide();
  };
}

export function hideBackButton(): void {
  getWebApp()?.BackButton.hide();
}
