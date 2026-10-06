/**
 * Minimal chiziqli SVG ikonkalar. DESIGN.md: emoji YO'Q — bu to'plam
 * bottom-nav, header va mahsulot kartasidagi barcha grafik belgilarni
 * almashtiradi. stroke=currentColor — rangni ota elementning `color`si
 * belgilaydi (masalan `.tab` aktiv holatda --pri ga o'tadi).
 */

export type IconName =
  | "home"
  | "grid"
  | "search"
  | "cart"
  | "orders"
  | "user"
  | "shield"
  | "crown"
  | "heart"
  | "heart-filled"
  | "plus"
  | "minus"
  | "check"
  | "chevron-right"
  | "box"
  | "alert"
  | "trash"
  | "edit"
  | "sparkle"
  | "arrow-up"
  | "arrow-down"
  | "percent"
  | "bell"
  | "globe";

const PATHS: Record<IconName, string> = {
  home: '<path d="M4 11.5 12 4l8 7.5"/><path d="M6 10v9h5v-5h2v5h5v-9"/>',
  grid: '<rect x="4" y="4" width="7" height="7" rx="1.2"/><rect x="13" y="4" width="7" height="7" rx="1.2"/><rect x="4" y="13" width="7" height="7" rx="1.2"/><rect x="13" y="13" width="7" height="7" rx="1.2"/>',
  search: '<circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.3-4.3"/>',
  cart: '<circle cx="9.5" cy="20" r="1.4"/><circle cx="17.5" cy="20" r="1.4"/><path d="M3 4h2l2.2 11.2a2 2 0 0 0 2 1.6h8.1a2 2 0 0 0 2-1.6L21 8H6"/>',
  orders: '<rect x="5" y="3.5" width="14" height="17" rx="1.6"/><path d="M9 8h6M9 12h6M9 16h3.5"/>',
  user: '<circle cx="12" cy="8.2" r="3.4"/><path d="M5 20c0-3.6 3.1-6.2 7-6.2s7 2.6 7 6.2"/>',
  shield: '<path d="M12 3.5 5 6.2v5.3c0 4.4 2.9 7.9 7 9 4.1-1.1 7-4.6 7-9V6.2L12 3.5Z"/><path d="m9.2 12 2 2 3.6-4"/>',
  crown: '<path d="M4 8.5 7.5 12l4.5-6.5L16.5 12 20 8.5 18.5 17h-13L4 8.5Z"/><path d="M6.5 20h11"/>',
  heart: '<path d="M12 20.2s-7.6-4.6-9.6-9.4C1 7.2 3 4 6.5 4c2 0 3.6 1.1 4.5 2.6C11.9 5.1 13.5 4 15.5 4 19 4 21 7.2 19.6 10.8 17.6 15.6 12 20.2 12 20.2Z"/>',
  "heart-filled": '<path d="M12 20.2s-7.6-4.6-9.6-9.4C1 7.2 3 4 6.5 4c2 0 3.6 1.1 4.5 2.6C11.9 5.1 13.5 4 15.5 4 19 4 21 7.2 19.6 10.8 17.6 15.6 12 20.2 12 20.2Z" fill="currentColor" stroke="none"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  minus: '<path d="M5 12h14"/>',
  check: '<path d="m5 13 4.5 4.5L19 8"/>',
  "chevron-right": '<path d="m9 6 6 6-6 6"/>',
  box: '<path d="M3.5 8 12 3.5 20.5 8 12 12.5 3.5 8Z"/><path d="M3.5 8v9l8.5 4.5M20.5 8v9L12 21.5M12 12.5V21.5"/>',
  alert: '<path d="M12 3.5 21.5 20h-19L12 3.5Z"/><path d="M12 10v4.5"/><circle cx="12" cy="17.3" r="0.9" fill="currentColor" stroke="none"/>',
  trash: '<path d="M5 7h14M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2m3 0-.8 12a2 2 0 0 1-2 1.8H8.8a2 2 0 0 1-2-1.8L6 7"/><path d="M10 11v6M14 11v6"/>',
  edit: '<path d="M4 20h4l10.5-10.5a2 2 0 0 0-4-4L4 16v4Z"/><path d="m13.5 6.5 4 4"/>',
  sparkle: '<path d="M12 3v4M12 17v4M3 12h4M17 12h4"/><path d="m6.5 6.5 2 2M15.5 15.5l2 2M17.5 6.5l-2 2M6.5 17.5l2-2"/><circle cx="12" cy="12" r="2.4"/>',
  "arrow-up": '<path d="M12 19V5"/><path d="m6 11 6-6 6 6"/>',
  "arrow-down": '<path d="M12 5v14"/><path d="m18 13-6 6-6-6"/>',
  percent: '<path d="M6 6 18 18"/><circle cx="7.5" cy="7.5" r="2"/><circle cx="16.5" cy="16.5" r="2"/>',
  bell: '<path d="M6 9a6 6 0 0 1 12 0c0 4 1.5 5.5 1.5 5.5H4.5S6 13 6 9Z"/><path d="M10 19a2 2 0 0 0 4 0"/>',
  globe: '<circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17M12 3.5c2.2 2.3 3.3 5.3 3.3 8.5s-1.1 6.2-3.3 8.5c-2.2-2.3-3.3-5.3-3.3-8.5S9.8 5.8 12 3.5Z"/>',
};

export function icon(name: IconName, size = 20): HTMLElement {
  const wrap = document.createElement("span");
  wrap.className = "icon";
  wrap.setAttribute("aria-hidden", "true");
  wrap.innerHTML =
    `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" ` +
    `stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">` +
    `${PATHS[name]}</svg>`;
  return wrap;
}
