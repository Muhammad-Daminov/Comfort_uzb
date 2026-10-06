import type { ProductListItem } from "../api/catalog";
import { navigate } from "../router";
import { priceTag } from "./price-tag";
import { badge } from "./badge";
import { productMedia } from "./product-media";
import { icon } from "./icons";
import { uz } from "../locale";

export interface ProductCardOptions {
  /** Karta brendi — 9.5/700 UPPERCASE, --pri. */
  brandName?: string;
  /** Moslik qatori: "Nexia 3 2016–24". Yil oralig'i MAJBURIY (DESIGN.md) —
   *  xaridorning birinchi savoli "mening mashinamga tushadimi". */
  fitment?: string;
  /** Chegirmadan oldingi narx; foizi chap tepadagi belgida chiqadi. */
  oldPrice?: number | null;
  /** Savatga qo'shish — narx qatoridagi [+]. Berilmasa chizilmaydi. */
  onAdd?: (product: ProductListItem) => void;
  /** Sevimlilar P1 va backendda endpoint yo'q. Yurak faqat ishlov beruvchi
   *  berilganda chiziladi — hech narsa qilmaydigan tugma ko'rsatilmaydi. */
  onToggleFavorite?: (product: ProductListItem) => void;
  isFavorite?: boolean;
}

/** Do'konning yuzi. Tuzilishi DESIGN.md dan aynan: rasm 1:1 → brend →
 *  nom (2 qator) → moslik → narx qatori. */
export function productCard(product: ProductListItem, options: ProductCardOptions = {}): HTMLElement {
  const card = document.createElement("button");
  card.type = "button";
  card.className = "product-card";
  card.addEventListener("click", () => navigate(`/product/${product.id}`));

  const inStock = product.total_available > 0;
  const brandName = options.brandName ?? product.brand_name ?? undefined;
  const oldPrice = options.oldPrice ?? product.old_price;
  const fitment = options.fitment ?? fitmentLine(product);

  // ---- rasm ----
  // Rasm yo'q yoki yuklanmadi — `productMedia` bir xil o'rin bosuvchini
  // beradi (siluet + bosh harf), savat va admin ro'yxati bilan aynan bir xil.
  const media = productMedia(product.primary_image_url, product.name, { size: "full" });

  // Chap tepa: tugagan chegirmadan ustun — mavjud bo'lmagan mahsulot
  // hech qachon aksiya kabi ko'rinmaydi.
  const flag = document.createElement("div");
  flag.className = "product-flag";
  if (!inStock) {
    flag.appendChild(badge(uz.outOfStock, "dang"));
    media.appendChild(flag);
  } else if (oldPrice != null && oldPrice > product.min_price) {
    const percent = Math.round(((oldPrice - product.min_price) / oldPrice) * 100);
    flag.appendChild(badge(`−${percent}%`, "acc"));
    media.appendChild(flag);
  }

  if (options.onToggleFavorite) {
    const fav = document.createElement("button");
    fav.type = "button";
    fav.className = "product-fav";
    fav.appendChild(icon(options.isFavorite ? "heart-filled" : "heart", 15));
    fav.setAttribute("aria-label", "Sevimlilarga qo'shish");
    fav.setAttribute("aria-pressed", String(Boolean(options.isFavorite)));
    fav.addEventListener("click", (event) => {
      event.stopPropagation(); // yurak bosilganda mahsulotga o'tmaydi
      options.onToggleFavorite?.(product);
    });
    media.appendChild(fav);
  }
  card.appendChild(media);

  // ---- matn ----
  const body = document.createElement("div");
  body.className = "product-body";

  if (brandName) {
    const brand = document.createElement("div");
    brand.className = "t-brand";
    brand.textContent = brandName;
    body.appendChild(brand);
  }

  const name = document.createElement("div");
  name.className = "product-name";
  name.textContent = product.name; // faqat textContent (§12.1)
  body.appendChild(name);

  if (fitment) {
    const fit = document.createElement("div");
    fit.className = "product-fit";
    fit.textContent = fitment;
    body.appendChild(fit);
  }

  const priceRow = document.createElement("div");
  priceRow.className = "product-price-row";
  priceRow.appendChild(priceTag(product.min_price, { oldPrice }));

  if (options.onAdd && inStock) {
    const add = document.createElement("button");
    add.type = "button";
    add.className = "product-add";
    add.appendChild(icon("plus", 15));
    add.setAttribute("aria-label", "Savatga qo'shish");
    add.addEventListener("click", (event) => {
      event.stopPropagation();
      options.onAdd?.(product);
    });
    priceRow.appendChild(add);
  }
  body.appendChild(priceRow);

  card.appendChild(body);
  return card;
}


/** "Nexia 3 2016–2024 · yana 4 ta" — xaridor ro'yxat kesilganini bilishi
 *  shart, aks holda ko'rsatilgan ikkitasi boshqa model bo'lsa, o'ziniki bor
 *  mahsulotni ko'rmay o'tib ketadi. */
function fitmentLine(product: ProductListItem): string | undefined {
  if (!product.fitment_summary) return undefined;
  const shown = product.fitment_summary.split(", ").length;
  const hidden = (product.fitment_total ?? 0) - shown;
  return hidden > 0 ? `${product.fitment_summary} · yana ${hidden} ta` : product.fitment_summary;
}
