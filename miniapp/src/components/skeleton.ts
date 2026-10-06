/** Yuklanish har doim skeleton, spinner emas (DESIGN.md): u haqiqiy
 *  joylashuvni band qiladi, shuning uchun ma'lumot kelganda ekran
 *  sakramaydi. */
export function skeletonBlock(height: number, radius: "sm" | "card" = "sm"): HTMLElement {
  const el = document.createElement("div");
  el.className = radius === "card" ? "skeleton skeleton-card" : "skeleton";
  el.style.height = `${height}px`;
  return el;
}

/** Mahsulot to'rining aynan shakli — kartaga o'tish sezilmaydi. */
export function skeletonProductGrid(count = 6): HTMLElement {
  const grid = document.createElement("div");
  grid.className = "product-grid";
  for (let i = 0; i < count; i++) {
    const cell = document.createElement("div");
    cell.className = "skeleton skeleton-card skeleton-tile";
    grid.appendChild(cell);
  }
  return grid;
}
