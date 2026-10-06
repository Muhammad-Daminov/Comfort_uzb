export type ButtonVariant = "pri" | "sec" | "out" | "dang";

export interface ButtonOptions {
  variant?: ButtonVariant;
  block?: boolean;
  small?: boolean;
  disabled?: boolean;
  onClick?: () => void;
}

/** DESIGN.md "Tugmalar". Har bir amal shu yerdan o'tadi — shuning uchun
 *  o'lcham, bosilish javobi (opacity .85 + scale .98) va rang hamma joyda
 *  bir xil. `type="button"` ataylab: tugmalar ko'pincha forma ichida
 *  turadi va uni yubormasligi kerak. */
export function button(label: string, options: ButtonOptions = {}): HTMLButtonElement {
  const el = document.createElement("button");
  el.type = "button";
  el.textContent = label; // faqat textContent, hech qachon innerHTML (§12.1)

  const classes = ["btn", `btn-${options.variant ?? "pri"}`];
  if (options.block) classes.push("btn-block");
  if (options.small) classes.push("btn-sm");
  el.className = classes.join(" ");

  if (options.disabled) el.disabled = true;
  if (options.onClick) el.addEventListener("click", options.onClick);
  return el;
}

/** Yumaloq mayda tugma: yopish, +/−, yurak. `label` — ekran o'quvchisi
 *  uchun nom, `glyph` — ko'rinadigan belgi. */
export function iconButton(glyph: string, label: string, onClick?: () => void): HTMLButtonElement {
  const el = document.createElement("button");
  el.type = "button";
  el.className = "btn btn-out btn-icon";
  el.textContent = glyph;
  el.setAttribute("aria-label", label);
  if (onClick) el.addEventListener("click", onClick);
  return el;
}
