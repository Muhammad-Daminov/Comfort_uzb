import { adminListOrders } from "../../api/admin";
import type { OrderResponse } from "../../api/orders";
import { formatSom } from "../../components/price";
import { skeletonList } from "../../components/loading";
import { emptyState } from "../../components/empty-state";
import { errorState } from "../../components/error-state";
import { icon } from "../../components/icons";
import { setBackButton } from "../../telegram";
import { navigate } from "../../router";

// Visual-only migration to the premium design system (§P3B-1) — same
// API call, same statuses, same navigation target as before.

const STATUS_FILTERS: Array<[string, string]> = [
  ["", "Barchasi"],
  ["UNDER_REVIEW", "Ko'rib chiqilmoqda"],
  ["PAYMENT_SUBMITTED", "To'lov yuborildi"],
  ["CONFIRMED", "Tasdiqlandi"],
  ["CANCELLED", "Bekor qilindi"],
];

const ORDER_STATUS_LABEL: Record<string, string> = {
  CREATED: "Yaratildi",
  AWAITING_PAYMENT: "To'lov kutilmoqda",
  PAYMENT_SUBMITTED: "To'lov yuborildi",
  UNDER_REVIEW: "Ko'rib chiqilmoqda",
  CONFIRMED: "Tasdiqlandi",
  REJECTED: "Rad etildi",
  CANCELLED: "Bekor qilindi",
  EXPIRED: "Muddati o'tdi",
};

const ORDER_STATUS_BADGE: Record<string, string> = {
  CREATED: "badge",
  AWAITING_PAYMENT: "badge badge-warn",
  PAYMENT_SUBMITTED: "badge badge-warn",
  UNDER_REVIEW: "badge badge-warn",
  CONFIRMED: "badge badge-ok",
  REJECTED: "badge badge-dang",
  CANCELLED: "badge badge-dang",
  EXPIRED: "badge badge-dang",
};

function formatDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleDateString("uz-UZ", { day: "2-digit", month: "long", year: "numeric" });
}

function orderCard(order: OrderResponse): HTMLElement {
  const card = document.createElement("button");
  card.type = "button";
  card.className = "card card-tap mb-12";
  card.style.width = "100%";
  card.addEventListener("click", () => navigate(`/admin/order/${order.id}`));

  const top = document.createElement("div");
  top.className = "row-between mb-8";

  const number = document.createElement("div");
  number.className = "t-label num";
  number.textContent = order.order_number;
  top.appendChild(number);

  const statusBadge = document.createElement("span");
  statusBadge.className = ORDER_STATUS_BADGE[order.status] ?? "badge";
  statusBadge.textContent = ORDER_STATUS_LABEL[order.status] ?? order.status;
  top.appendChild(statusBadge);

  card.appendChild(top);

  const date = document.createElement("div");
  date.className = "hint mb-8";
  date.textContent = formatDate(order.created_at);
  card.appendChild(date);

  const bottom = document.createElement("div");
  bottom.className = "row-between";

  const total = document.createElement("div");
  total.className = "price-now";
  total.textContent = formatSom(order.total_amount);
  bottom.appendChild(total);

  card.appendChild(bottom);
  card.appendChild(icon("chevron-right", 16));

  return card;
}

export async function render(container: HTMLElement): Promise<void> {
  container.replaceChildren();
  setBackButton(() => navigate("/admin"));

  const header = document.createElement("h1");
  header.className = "screen-title";
  header.textContent = "Buyurtmalar";
  container.appendChild(header);

  const filterBar = document.createElement("div");
  filterBar.className = "chip-row mb-16";
  container.appendChild(filterBar);

  const listSection = document.createElement("div");
  container.appendChild(listSection);

  let activeStatus = "UNDER_REVIEW";
  const chips = new Map<string, HTMLButtonElement>();

  async function load(status: string): Promise<void> {
    activeStatus = status;
    for (const [value, chip] of chips) chip.setAttribute("aria-pressed", String(value === status));

    listSection.replaceChildren();
    listSection.appendChild(skeletonList(4, 90));
    try {
      const response = await adminListOrders(status || undefined);
      listSection.replaceChildren();
      if (response.items.length === 0) {
        listSection.appendChild(emptyState("Bu holatda buyurtmalar yo'q.", undefined, "orders"));
        return;
      }
      for (const order of response.items) {
        listSection.appendChild(orderCard(order));
      }
    } catch (error) {
      listSection.replaceChildren();
      listSection.appendChild(errorState(error, () => void load(status)));
    }
  }

  for (const [status, label] of STATUS_FILTERS) {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "chip";
    chip.setAttribute("aria-pressed", String(status === activeStatus));
    chip.textContent = label;
    chip.addEventListener("click", () => void load(status));
    chips.set(status, chip);
    filterBar.appendChild(chip);
  }

  await load(activeStatus);
}
