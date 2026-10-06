import { listOrders, type OrderListItem } from "../api/orders";
import { formatSom } from "../components/price";
import { skeletonList } from "../components/loading";
import { emptyState } from "../components/empty-state";
import { errorState } from "../components/error-state";
import { icon } from "../components/icons";
import { setBackButton, hideMainButton } from "../telegram";
import { navigate } from "../router";

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

const PAYMENT_STATUS_LABEL: Record<string, string> = {
  PENDING: "To'lov kutilmoqda",
  APPROVED: "To'lov tasdiqlangan",
  REJECTED: "To'lov rad etilgan",
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

function productsSummary(items: OrderListItem["items"]): string {
  if (!items || items.length === 0) return "";
  return items.map((line) => `${line.product_name} × ${line.quantity}`).join(", ");
}

function orderCard(order: OrderListItem): HTMLElement {
  const card = document.createElement("button");
  card.type = "button";
  card.className = "card card-tap mb-12";
  card.style.width = "100%";
  card.addEventListener("click", () => navigate(`/order/${order.id}`));

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

  const summary = productsSummary(order.items);
  if (summary) {
    const products = document.createElement("div");
    products.className = "t-body mb-8";
    products.style.color = "var(--text2)";
    products.textContent = summary;
    card.appendChild(products);
  }

  const bottom = document.createElement("div");
  bottom.className = "row-between";

  const total = document.createElement("div");
  total.className = "price-now";
  total.textContent = formatSom(order.total_amount);
  bottom.appendChild(total);

  if (order.latest_payment_status) {
    const paymentBadge = document.createElement("span");
    paymentBadge.className = "hint";
    paymentBadge.textContent = PAYMENT_STATUS_LABEL[order.latest_payment_status] ?? order.latest_payment_status;
    bottom.appendChild(paymentBadge);
  }

  card.appendChild(bottom);
  card.appendChild(icon("chevron-right", 16));

  return card;
}

export async function render(container: HTMLElement): Promise<void> {
  container.replaceChildren();
  setBackButton(() => navigate("/home"));
  hideMainButton();

  const header = document.createElement("h1");
  header.className = "screen-title";
  header.textContent = "Buyurtmalar";
  container.appendChild(header);

  const listSection = document.createElement("div");
  container.appendChild(listSection);
  listSection.appendChild(skeletonList(3, 140));

  try {
    const response = await listOrders();
    listSection.innerHTML = "";
    if (response.items.length === 0) {
      listSection.appendChild(
        emptyState(
          "Hali buyurtmalaringiz yo'q. Katalogdan sidena tanlab, birinchi buyurtmangizni bering.",
          { label: "Katalogni ko'rish", onClick: () => navigate("/catalog") },
          "orders",
        ),
      );
      return;
    }
    for (const order of response.items) {
      listSection.appendChild(orderCard(order));
    }
  } catch (error) {
    listSection.innerHTML = "";
    listSection.appendChild(errorState(error, () => void render(container)));
  }
}
