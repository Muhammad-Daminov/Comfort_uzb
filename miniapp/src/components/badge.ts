export type BadgeTone = "neutral" | "pri" | "acc" | "ok" | "warn" | "dang";

/** Holat belgisi. Ton — ma'no, bezak emas: ok = mavjud/tasdiqlangan,
 *  warn = kam qoldi, dang = tugagan/bekor, acc = chegirma/yangi. */
export function badge(text: string, tone: BadgeTone = "neutral"): HTMLElement {
  const el = document.createElement("span");
  el.className = tone === "neutral" ? "badge" : `badge badge-${tone}`;
  el.textContent = text;
  return el;
}
