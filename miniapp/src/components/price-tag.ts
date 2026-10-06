import { formatSom } from "./price";

export interface PriceTagOptions {
  /** Chegirmadan oldingi narx. Faqat haqiqatan yuqori bo'lsa chiziladi —
   *  bezak uchun emas. */
  oldPrice?: number | null;
  /** 19/900 — detal ekrani va pastki panel uchun. */
  large?: boolean;
}

/** Narx ekrandagi eng qat'iy element. tabular-nums MAJBURIY (DESIGN.md):
 *  aks holda ro'yxatda raqamlar qalqib turadi. */
export function priceTag(amount: number, options: PriceTagOptions = {}): HTMLElement {
  const wrapper = document.createElement("div");
  wrapper.className = options.large ? "price price-lg" : "price";

  const now = document.createElement("span");
  now.className = "price-now";
  now.textContent = formatSom(amount);
  wrapper.appendChild(now);

  if (options.oldPrice != null && options.oldPrice > amount) {
    const was = document.createElement("span");
    was.className = "price-was";
    was.textContent = formatSom(options.oldPrice);
    wrapper.appendChild(was);
  }

  return wrapper;
}
