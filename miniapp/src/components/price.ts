/** §5.1: pul — butun so'm (BIGINT, float yo'q, tiyin yo'q). Mingliklar
 * oddiy bo'sh joy bilan ajratiladi — "uz-UZ" ICU ma'lumoti hamma joyda
 * bir xil emas va uning ajratuvchisi U+0020 bo'lishi kafolatlanmagan. */
export function formatSom(amount: number): string {
  const grouped = Math.trunc(amount).toString().replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  return `${grouped} so'm`;
}

/** Eski imzo — bir nechta ekran hali shuni chaqiradi. Ichi endi
 *  price-tag bilan bir xil klasslarni ishlatadi (tabular-nums majburiy). */
export function priceElement(currentPrice: number, discountAmount: number, basePrice?: number): HTMLElement {
  const wrapper = document.createElement("div");
  wrapper.className = "price";

  const current = document.createElement("span");
  current.className = "price-now";
  current.textContent = formatSom(currentPrice);
  wrapper.appendChild(current);

  if (discountAmount > 0 && basePrice !== undefined) {
    const original = document.createElement("span");
    original.className = "price-was";
    original.textContent = formatSom(basePrice);
    wrapper.appendChild(original);
  }

  return wrapper;
}
