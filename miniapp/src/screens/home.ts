import { listProducts } from "../api/catalog";
import { listOrders } from "../api/orders";
import { productCard } from "../components/product-card";
import { skeletonList } from "../components/loading";
import { emptyState } from "../components/empty-state";
import { errorState } from "../components/error-state";
import { icon } from "../components/icons";
import { navigate } from "../router";
import { hideBackButton } from "../telegram";

export async function render(container: HTMLElement): Promise<void> {
  container.replaceChildren(); // retry re-renders into the same container — never stack a second copy
  hideBackButton();

  container.appendChild(brandHeader());
  container.appendChild(hero());
  container.appendChild(categoryRow());

  const recentSection = document.createElement("div");
  container.appendChild(recentSection);
  void renderRecentOrder(recentSection);

  container.appendChild(sectionHeader("Mahsulotlar", "Hammasi", "/catalog"));

  const productsSection = document.createElement("div");
  container.appendChild(productsSection);
  productsSection.appendChild(skeletonList(4, 100));

  try {
    const response = await listProducts({ limit: 10 });
    productsSection.innerHTML = "";
    if (response.items.length === 0) {
      productsSection.appendChild(
        emptyState(
          "Katalog hozircha to'ldirilmoqda. Tez orada premium sidena va sidena chexollari shu yerda paydo bo'ladi.",
          undefined,
        ),
      );
    } else {
      const grid = document.createElement("div");
      grid.className = "product-grid";
      for (const product of response.items) {
        grid.appendChild(productCard(product));
      }
      productsSection.appendChild(grid);
    }
  } catch (error) {
    productsSection.innerHTML = "";
    productsSection.appendChild(errorState(error, () => void render(container)));
  }
}

/** Brend sarlavhasi: wordmark + qidiruv/savat ikonkalari. Emoji yo'q —
 *  DESIGN.md "Ikonka" bo'limi, icons.ts dan SVG. */
function brandHeader(): HTMLElement {
  const header = document.createElement("div");
  header.className = "brand-header";

  const wordmark = document.createElement("div");
  wordmark.className = "brand-wordmark";
  wordmark.textContent = "COMFORT UZB";
  header.appendChild(wordmark);

  const actions = document.createElement("div");
  actions.className = "brand-header-actions";

  const search = document.createElement("button");
  search.type = "button";
  search.className = "brand-icon-btn";
  search.setAttribute("aria-label", "Qidiruv");
  search.appendChild(icon("search", 19));
  search.addEventListener("click", () => navigate("/search"));
  actions.appendChild(search);

  const cart = document.createElement("button");
  cart.type = "button";
  cart.className = "brand-icon-btn";
  cart.setAttribute("aria-label", "Savat");
  cart.appendChild(icon("cart", 19));
  cart.addEventListener("click", () => navigate("/cart"));
  actions.appendChild(cart);

  header.appendChild(actions);
  return header;
}

/** Premium hero — do'kon nimani sotishini birinchi soniyada aytadi. */
function hero(): HTMLElement {
  const section = document.createElement("section");
  section.className = "hero";

  const eyebrow = document.createElement("div");
  eyebrow.className = "hero-eyebrow";
  eyebrow.textContent = "Premium sidena";
  section.appendChild(eyebrow);

  const title = document.createElement("h2");
  title.className = "hero-title";
  title.textContent = "Qulaylik — o'rindig'ingiz uchun.";
  section.appendChild(title);

  const sub = document.createElement("p");
  sub.className = "hero-sub";
  sub.textContent = "Har bir avtomobil modeliga mos, sifatli materialdan tikilgan sidena va sidena chexollari.";
  section.appendChild(sub);

  const cta = document.createElement("button");
  cta.type = "button";
  cta.className = "btn btn-pri";
  cta.textContent = "Katalogni ko'rish";
  cta.addEventListener("click", () => navigate("/catalog"));
  section.appendChild(cta);

  return section;
}

/** Faqat ikkita real toifa (business context §1) — "Barchasi" katalogga,
 *  qolgan ikkitasi ham hozircha katalogga o'tadi: backendda alohida
 *  category maydoni yo'q (faqat brand/car/color filtrlari bor), shuning
 *  uchun bu yerda yangi filtr API'si o'ylab topilmaydi — chip'lar vizual
 *  toifalash, katalog ekranining o'zi to'liq ro'yxatni ko'rsatadi. */
function categoryRow(): HTMLElement {
  const row = document.createElement("div");
  row.className = "category-row";

  const items: Array<{ label: string; pressed: boolean }> = [
    { label: "Barchasi", pressed: true },
    { label: "Sidena", pressed: false },
    { label: "Sidena chexollari", pressed: false },
  ];

  for (const item of items) {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "category-chip";
    chip.textContent = item.label;
    chip.setAttribute("aria-pressed", String(item.pressed));
    chip.addEventListener("click", () => navigate("/catalog"));
    row.appendChild(chip);
  }

  return row;
}

/** "Mahsulotlar ————— Hammasi ›" */
function sectionHeader(titleText: string, linkText: string, path: string): HTMLElement {
  const row = document.createElement("div");
  row.className = "section-header";

  const title = document.createElement("div");
  title.className = "section-title";
  title.textContent = titleText;
  row.appendChild(title);

  const link = document.createElement("button");
  link.type = "button";
  link.className = "section-link";
  link.textContent = linkText;
  link.appendChild(icon("chevron-right", 14));
  link.addEventListener("click", () => navigate(path));
  row.appendChild(link);

  return row;
}

/** Order-history *list* is P1 (docs/02_FEATURE_INVENTORY.md) — order detail
 *  is P0. This links straight to the single most recent order via the same
 *  GET /orders the backend already exposes, without building the deferred
 *  list screen. Non-critical: Home still renders if it fails. */
async function renderRecentOrder(section: HTMLElement): Promise<void> {
  try {
    const orders = await listOrders();
    if (orders.items.length === 0) return;
    const recent = orders.items[0];

    const heading = document.createElement("div");
    heading.className = "section-title";
    heading.textContent = "So'nggi buyurtma";
    section.appendChild(heading);

    const card = document.createElement("button");
    card.type = "button";
    card.className = "list list-item";
    card.addEventListener("click", () => navigate(`/order/${recent.id}`));

    const text = document.createElement("span");
    text.className = "grow";
    const number = document.createElement("div");
    number.className = "list-title num";
    number.textContent = recent.order_number;
    text.appendChild(number);
    const status = document.createElement("div");
    status.className = "list-sub";
    status.textContent = recent.status;
    text.appendChild(status);
    card.appendChild(text);

    card.appendChild(icon("chevron-right", 16));

    section.appendChild(card);
  } catch {
    // Non-critical — Home still works without the recent-order card.
  }
}
