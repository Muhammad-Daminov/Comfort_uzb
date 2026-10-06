export interface ChipOptions {
  active?: boolean;
  onClick?: () => void;
}

/** Filtr/tanlov chipi. Holat `aria-pressed` da — ekran o'quvchisi ham,
 *  CSS ham bir manbadan o'qiydi, ikkita haqiqat bo'lmaydi. */
export function chip(label: string, options: ChipOptions = {}): HTMLButtonElement {
  const el = document.createElement("button");
  el.type = "button";
  el.className = "chip";
  el.textContent = label;
  el.setAttribute("aria-pressed", String(Boolean(options.active)));
  if (options.onClick) el.addEventListener("click", options.onClick);
  return el;
}

/** Gorizontal siljiydigan chip qatori. */
export function chipRow(chips: HTMLElement[]): HTMLElement {
  const row = document.createElement("div");
  row.className = "chip-row";
  for (const item of chips) row.appendChild(item);
  return row;
}
