/**
 * Qo'zg'almas pastki navigatsiya (Uzum/Wildberries modeli).
 *
 * Nega tepada emas: telefonda barmoq pastda turadi va scroll qilinganda
 * tepadagi tugmalar ko'rinmay qoladi — oldingi "action-tile" qatori aynan
 * shu sababdan yo'qotilgan.
 *
 * Panel `#app` dan TASHQARIDA, `document.body` da yashaydi: router har
 * navigatsiyada `#app` ni butunlay tozalaydi, ichida bo'lsa panel ham
 * o'chib ketardi. Shuning uchun u bir marta o'rnatiladi va keyin faqat
 * aktiv holatini yangilaydi.
 *
 * Rollar UX darajasida: Admin/Owner tablari faqat mos rolda chiziladi.
 * Bu xavfsizlik chegarasi EMAS — har bir /admin/* va /owner/* endpoint
 * o'z ruxsatini serverda mustaqil tekshiradi
 * (tests/integration/test_admin_permissions_boundary.py).
 */
import { navigate } from "../router";
import { isAdminRole, isOwnerRole } from "../state/session";
import { icon as renderIcon, type IconName } from "./icons";

interface Tab {
  /** Bosilganda o'tiladigan yo'l. */
  path: string;
  icon: IconName;
  label: string;
  /** Shu tab aktiv sanaladigan yo'l boshlanmalari. */
  owns: string[];
}

export function tabsForRole(admin: boolean, owner: boolean): Tab[] {
  const tabs: Tab[] = [
    // Katalog va mahsulot sahifalari "Asosiy" ostida — ular bir xil
    // ko'rish oqimining davomi, alohida tab emas.
    { path: "/home", icon: "home", label: "Asosiy", owns: ["/home", "/catalog", "/product"] },
    { path: "/cart", icon: "cart", label: "Savat", owns: ["/cart", "/checkout"] },
    { path: "/orders", icon: "orders", label: "Buyurtmalar", owns: ["/orders", "/order", "/payment", "/receipt"] },
  ];
  tabs.push({ path: "/profile", icon: "user", label: "Profil", owns: ["/profile"] });
  // §12/§13: Admin/Owner uchun alohida, avtomatik ko'rinadigan yo'l —
  // Settings/Profile ichiga yashirilmaydi, oddiy USER'ga umuman chizilmaydi.
  if (admin) tabs.push({ path: "/admin", icon: "shield", label: "Admin panel", owns: ["/admin"] });
  if (owner) tabs.push({ path: "/owner", icon: "crown", label: "Boshqaruv", owns: ["/owner"] });
  return tabs;
}

/** `/admin/product/3` → `/admin` tabi. Eng uzun mos keluvchi yutadi, aks
 *  holda `/owner` ham `/o...` bilan chalkashadi. */
export function activeTabPath(tabs: Tab[], hashPath: string): string | null {
  let best: { path: string; length: number } | null = null;
  for (const tab of tabs) {
    for (const prefix of tab.owns) {
      const matches = hashPath === prefix || hashPath.startsWith(prefix + "/");
      if (matches && (!best || prefix.length > best.length)) {
        best = { path: tab.path, length: prefix.length };
      }
    }
  }
  return best ? best.path : null;
}

function currentPath(): string {
  const raw = window.location.hash.slice(1);
  return raw.startsWith("/") ? raw : "/home";
}

export function mountTabBar(host: HTMLElement = document.body): HTMLElement {
  const existing = host.querySelector<HTMLElement>(".tabbar");
  if (existing) existing.remove();

  const tabs = tabsForRole(isAdminRole(), isOwnerRole());

  const nav = document.createElement("nav");
  nav.className = "tabbar";
  nav.setAttribute("aria-label", "Asosiy navigatsiya");

  const buttons = tabs.map((tab) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "tab";
    button.addEventListener("click", () => navigate(tab.path));

    const iconEl = renderIcon(tab.icon, 22);
    iconEl.classList.add("tab-icon");
    button.appendChild(iconEl);

    // Yorliq har doim ko'rinadi — faqat ikonka nimani anglatishini
    // foydalanuvchi taxmin qilishi kerak bo'lardi.
    const label = document.createElement("span");
    label.className = "tab-label";
    label.textContent = tab.label;
    button.appendChild(label);

    nav.appendChild(button);
    return { tab, button };
  });

  function syncActive(): void {
    const active = activeTabPath(tabs, currentPath());
    for (const { tab, button } of buttons) {
      if (tab.path === active) button.setAttribute("aria-current", "page");
      else button.removeAttribute("aria-current");
    }
  }

  syncActive();
  window.addEventListener("hashchange", syncActive);
  host.appendChild(nav);
  // Kontent panel ostida qolmasligi uchun — o'lchov CSS da.
  document.body.classList.add("has-tabbar");
  return nav;
}
