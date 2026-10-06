/**
 * In-memory session state only — §14.2: "localStorage ishlatilmaydi"
 * (localStorage is unreliable in the Telegram WebView). The token lives
 * for the lifetime of the page; a fresh `POST /auth/session` call happens
 * on every cold start (main.ts), which is cheap and matches the token's
 * own 24h server-side TTL (app/security/session.py).
 */

interface SessionState {
  token: string | null;
  userId: number | null;
  role: string | null;
}

const state: SessionState = { token: null, userId: null, role: null };

export function setSession(token: string, userId: number, role: string): void {
  state.token = token;
  state.userId = userId;
  state.role = role;
}

export function clearSession(): void {
  state.token = null;
  state.userId = null;
  state.role = null;
}

export function getToken(): string | null {
  return state.token;
}

export function getUserId(): number | null {
  return state.userId;
}

export function getRole(): string | null {
  return state.role;
}

export function isAuthenticated(): boolean {
  return state.token !== null;
}

/** UX-only gate for showing the Admin nav link (Phase 06) — never a
 * security boundary; every admin endpoint enforces its own permission
 * server-side regardless of what this returns. */
export function isAdminRole(): boolean {
  return state.role === "ADMIN" || state.role === "OWNER";
}

/** UX-only gate for the Owner nav link (Phase 07) — distinct from
 * `isAdminRole`: a plain ADMIN must NOT see Owner-only navigation, even
 * though ADMIN does see the Admin Panel link. Not a security boundary —
 * every /owner/* endpoint enforces its own permission server-side. */
export function isOwnerRole(): boolean {
  return state.role === "OWNER";
}
