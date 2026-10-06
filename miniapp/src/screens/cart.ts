import * as cartState from "../state/cart";
import type { CartItem } from "../api/cart";
import { formatSom } from "../components/price";
import { productMedia } from "../components/product-media";
import { skeletonList } from "../components/loading";
import { emptyState } from "../components/empty-state";
import { errorState } from "../components/error-state";
import { setBackButton, setMainButton, hideMainButton } from "../telegram";
import { navigate } from "../router";
import { icon } from "../components/icons";
import { uz } from "../locale";

export async function render(container: HTMLElement): Promise<void> {
  setBackButton(() => navigate("/home"));

  const header = document.createElement("h2");
  header.textContent = "Savat";
  container.appendChild(header);

  const listSection = document.createElement("div");
  container.appendChild(listSection);
  listSection.appendChild(skeletonList(3, 92));

  const totalSection = document.createElement("div");
  container.appendChild(totalSection);

  function itemRow(item: CartItem, onChange: (quantity: number) => void, onRemove: () => void): HTMLElement {
    const row = document.createElement("div");
    row.className = "media-row";

    // 72×72 rasm chapda — savatda mahsulotni nomidan ko'ra rasmidan
    // tanish osonroq, ayniqsa bir xil turkumdagi ikki mahsulot bo'lsa.
    row.appendChild(productMedia(item.primary_image_url, item.product_name, { size: "md" }));

    const body = document.createElement("div");
    body.className = "media-row-body";

    const name = document.createElement("div");
    name.className = "media-row-title";
    name.textContent = item.product_name;
    body.appendChild(name);

    const available = item.stock_on_hand - item.stock_reserved;
    const unavailable = item.variant_status !== "ACTIVE" || available < item.quantity;
    if (unavailable) {
      const warning = document.createElement("div");
      warning.className = "error-text";
      warning.textContent = uz.insufficientStock;
      body.appendChild(warning);
    } else {
      const price = document.createElement("div");
      price.className = "price";
      const now = document.createElement("span");
      now.className = "price-now";
      const current = cartState.unitPrice(item);
      now.textContent = formatSom(current);
      price.appendChild(now);
      if (current < item.price) {
        const old = document.createElement("span");
        old.className = "price-old";
        old.textContent = formatSom(item.price);
        price.appendChild(old);
      }
      body.appendChild(price);
    }

    const stepper = document.createElement("div");
    stepper.className = "stepper";

    const minus = document.createElement("button");
    minus.type = "button";
    minus.className = "stepper-btn";
    minus.textContent = "−";
    minus.setAttribute("aria-label", "Kamaytirish");
    minus.addEventListener("click", () => onChange(item.quantity - 1));
    stepper.appendChild(minus);

    const value = document.createElement("span");
    value.className = "stepper-value";
    value.textContent = String(item.quantity);
    stepper.appendChild(value);

    const plus = document.createElement("button");
    plus.type = "button";
    plus.className = "stepper-btn";
    plus.textContent = "+";
    plus.setAttribute("aria-label", "Ko'paytirish");
    // Mavjud zaxiradan oshirib bo'lmaydi — server baribir rad etadi
    // (§7.3), tugmani o'chirib qo'yish xatoni oldindan ko'rsatadi.
    plus.disabled = available <= item.quantity;
    plus.addEventListener("click", () => onChange(item.quantity + 1));
    stepper.appendChild(plus);

    body.appendChild(stepper);
    row.appendChild(body);

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "icon-btn icon-btn-dang";
    remove.appendChild(icon("trash", 16));
    remove.setAttribute("aria-label", "Savatdan olib tashlash");
    remove.addEventListener("click", onRemove);
    row.appendChild(remove);

    return row;
  }

  function renderItems(items: CartItem[]): void {
    listSection.innerHTML = "";
    totalSection.innerHTML = "";

    if (items.length === 0) {
      listSection.appendChild(emptyState(uz.emptyCart, undefined, "cart"));
      hideMainButton();
      return;
    }

    const list = document.createElement("div");
    list.className = "list";
    for (const item of items) {
      list.appendChild(
        itemRow(
          item,
          (quantity) => void mutate(() => updateQuantity(item, quantity)),
          () => void mutate(() => cartState.removeItem(item.id).then(() => refresh())),
        ),
      );
    }
    listSection.appendChild(list);

    const total = document.createElement("div");
    total.className = "row-between mt-12";
    const label = document.createElement("span");
    label.textContent = "Jami";
    total.appendChild(label);
    const amount = document.createElement("span");
    amount.className = "price-now";
    amount.textContent = formatSom(cartState.cartTotal(items));
    total.appendChild(amount);
    totalSection.appendChild(total);

    const validItems = items.filter(
      (i) => i.variant_status === "ACTIVE" && i.stock_on_hand - i.stock_reserved >= i.quantity,
    );
    if (validItems.length > 0) {
      setMainButton(uz.checkout, () => navigate("/checkout"));
    } else {
      hideMainButton();
    }
  }

  // Every stepper/remove tap used to be a bare `void promise` — a 422/401/
  // offline failure vanished without a word and the row kept its old
  // quantity. One in-flight mutation at a time, failures rendered.
  let mutating = false;
  async function mutate(action: () => Promise<void>): Promise<void> {
    if (mutating) return;
    mutating = true;
    try {
      await action();
    } catch (error) {
      listSection.prepend(errorState(error, () => void refresh()));
    } finally {
      mutating = false;
    }
  }

  async function updateQuantity(item: CartItem, quantity: number): Promise<void> {
    if (quantity <= 0) {
      await cartState.removeItem(item.id);
    } else {
      await cartState.updateItem(item.id, quantity);
    }
    await refresh();
  }

  async function refresh(): Promise<void> {
    try {
      const items = await cartState.loadCart();
      renderItems(items);
    } catch (error) {
      listSection.innerHTML = "";
      listSection.appendChild(errorState(error, () => void refresh()));
    }
  }

  await refresh();
}
