import { icon as renderIcon, type IconName } from "./icons";

export interface EmptyStateAction {
  label: string;
  onClick: () => void;
}

/** DESIGN.md: bo'sh ekran harakatga chorlaydi, kechirim so'ramaydi.
 *  `message` birinchi pozitsion argument bo'lib qoladi — mavjud
 *  chaqiruvlar o'zgarishsiz ishlaydi. Emoji yo'q — icons.ts dan SVG. */
export function emptyState(message: string, action?: EmptyStateAction, iconName: IconName = "box"): HTMLElement {
  const el = document.createElement("div");
  el.className = "state";

  const iconEl = renderIcon(iconName, 30);
  iconEl.classList.add("state-icon");
  el.appendChild(iconEl);

  const text = document.createElement("p");
  text.className = "state-text";
  text.textContent = message; // faqat textContent (§12.1)
  el.appendChild(text);

  if (action) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn btn-pri";
    btn.textContent = action.label;
    btn.addEventListener("click", action.onClick);
    el.appendChild(btn);
  }

  return el;
}
