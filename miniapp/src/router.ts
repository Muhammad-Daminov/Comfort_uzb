/**
 * Tiny hash-based router — no library, per the "smallest architecture
 * justified" plan decision. A route is a path pattern with `:param`
 * segments; the matching screen module's `render(container, params)` is
 * called with the mount point and parsed params.
 */

import { resetMainButton } from "./telegram";

export type ScreenRenderer = (container: HTMLElement, params: Record<string, string>) => void | Promise<void>;

interface Route {
  pattern: string;
  segments: string[];
  render: ScreenRenderer;
}

const routes: Route[] = [];
let container: HTMLElement | null = null;
let notFoundRenderer: ScreenRenderer | null = null;

export function registerRoute(pattern: string, render: ScreenRenderer): void {
  routes.push({ pattern, segments: pattern.split("/").filter(Boolean), render });
}

export function registerNotFound(render: ScreenRenderer): void {
  notFoundRenderer = render;
}

function matchRoute(hashPath: string): { route: Route; params: Record<string, string> } | null {
  const pathSegments = hashPath.split("/").filter(Boolean);
  for (const route of routes) {
    if (route.segments.length !== pathSegments.length) continue;
    const params: Record<string, string> = {};
    let matched = true;
    for (let i = 0; i < route.segments.length; i++) {
      const routeSegment = route.segments[i];
      const actualSegment = pathSegments[i];
      if (routeSegment.startsWith(":")) {
        params[routeSegment.slice(1)] = decodeURIComponent(actualSegment);
      } else if (routeSegment !== actualSegment) {
        matched = false;
        break;
      }
    }
    if (matched) return { route, params };
  }
  return null;
}

/**
 * Telegram launches a Mini App with its own parameters in the URL fragment
 * (`#tgWebAppData=...&tgWebAppVersion=...`) and `telegram-web-app.js` reads
 * them but never removes them. That fragment is not one of our routes, so
 * treating it as a path made every launch from inside Telegram land on
 * "Sahifa topilmadi." while a plain browser (no such fragment) worked fine.
 * Only a fragment that starts with `/` is ours; anything else means "no
 * route was requested" and gets the default screen.
 */
function readHashPath(): string {
  const raw = window.location.hash.slice(1);
  return raw.startsWith("/") ? raw : "/home";
}

/**
 * Every navigation renders into a brand-new child element and discards the
 * previous one. Screens are async and keep writing to their container after
 * awaits (`container.innerHTML = ""` after a fetch), so with a shared
 * container a slow screen the user had already left would wipe the screen
 * that replaced it. With a per-navigation mount those late writes land on
 * a detached node and are simply never seen. The MainButton is reset for
 * the same reason: it belongs to the screen, not to the app.
 */
async function handleRouteChange(): Promise<void> {
  if (!container) return;
  const hashPath = readHashPath();
  const match = matchRoute(hashPath);
  resetMainButton();
  const view = document.createElement("div");
  view.className = "view";
  container.replaceChildren(view);
  if (match) {
    await match.route.render(view, match.params);
  } else if (notFoundRenderer) {
    await notFoundRenderer(view, {});
  }
}

export function navigate(path: string): void {
  window.location.hash = path;
}

export function startRouter(mount: HTMLElement): void {
  container = mount;
  window.addEventListener("hashchange", () => void handleRouteChange());
  void handleRouteChange();
}
