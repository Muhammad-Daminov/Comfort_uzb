import { adminListPayments, adminReviewPayment, adminGetReceiptUrl } from "../../api/admin";
import type { PaymentResponse } from "../../api/payments";
import { formatSom } from "../../components/price";
import { skeletonList } from "../../components/loading";
import { emptyState } from "../../components/empty-state";
import { errorState } from "../../components/error-state";
import { setBackButton } from "../../telegram";
import { navigate } from "../../router";

// Visual-only migration to the premium design system (§P3B-1) — same
// endpoint calls, same PENDING-only listing, same approve/reject flow
// (destructive reject still confirms via a reason prompt, unchanged).

function paymentCard(payment: PaymentResponse, onChange: () => void, onError: (el: HTMLElement) => void): HTMLElement {
  const card = document.createElement("div");
  card.className = "card mb-12";

  const top = document.createElement("div");
  top.className = "row-between mb-8";

  const title = document.createElement("div");
  title.className = "list-title";
  title.textContent = `To'lov #${payment.id}`;
  top.appendChild(title);

  const amount = document.createElement("div");
  amount.className = "price-now";
  amount.textContent = formatSom(payment.amount);
  top.appendChild(amount);
  card.appendChild(top);

  const orderLine = document.createElement("div");
  orderLine.className = "hint mb-12";
  orderLine.textContent = `Buyurtma #${payment.order_id}`;
  card.appendChild(orderLine);

  const actions = document.createElement("div");
  actions.className = "row-between";
  actions.style.gap = "8px";

  const viewReceiptButton = document.createElement("button");
  viewReceiptButton.type = "button";
  viewReceiptButton.className = "btn btn-out btn-sm";
  viewReceiptButton.textContent = "Chekni ko'rish";
  viewReceiptButton.addEventListener("click", () => {
    void adminGetReceiptUrl(payment.id)
      .then(({ url }) => window.open(url, "_blank"))
      .catch((error: unknown) => onError(errorState(error)));
  });
  actions.appendChild(viewReceiptButton);

  const buttonGroup = document.createElement("div");
  buttonGroup.style.display = "flex";
  buttonGroup.style.gap = "8px";

  const rejectButton = document.createElement("button");
  rejectButton.type = "button";
  rejectButton.className = "btn btn-dang btn-sm";
  rejectButton.textContent = "Rad etish";
  rejectButton.addEventListener("click", () => {
    const reason = window.prompt("Rad etish sababi:");
    if (!reason) return;
    rejectButton.disabled = true;
    void adminReviewPayment(payment.id, false, reason)
      .then(onChange)
      .catch((error: unknown) => {
        rejectButton.disabled = false;
        onError(errorState(error));
      });
  });
  buttonGroup.appendChild(rejectButton);

  const approveButton = document.createElement("button");
  approveButton.type = "button";
  approveButton.className = "btn btn-pri btn-sm";
  approveButton.textContent = "Tasdiqlash";
  approveButton.addEventListener("click", () => {
    approveButton.disabled = true;
    void adminReviewPayment(payment.id, true)
      .then(onChange)
      .catch((error: unknown) => {
        approveButton.disabled = false;
        onError(errorState(error));
      });
  });
  buttonGroup.appendChild(approveButton);

  actions.appendChild(buttonGroup);
  card.appendChild(actions);

  return card;
}

export async function render(container: HTMLElement): Promise<void> {
  container.replaceChildren();
  setBackButton(() => navigate("/admin"));

  const header = document.createElement("h1");
  header.className = "screen-title";
  header.textContent = "To'lovlar";
  container.appendChild(header);

  const listSection = document.createElement("div");
  container.appendChild(listSection);

  async function load(): Promise<void> {
    listSection.replaceChildren();
    listSection.appendChild(skeletonList(3, 130));
    try {
      const response = await adminListPayments("PENDING");
      listSection.replaceChildren();
      if (response.items.length === 0) {
        listSection.appendChild(emptyState("Kutilayotgan to'lovlar yo'q.", undefined, "box"));
        return;
      }
      for (const payment of response.items) {
        listSection.appendChild(
          paymentCard(
            payment,
            () => void load(),
            (el) => listSection.appendChild(el),
          ),
        );
      }
    } catch (error) {
      listSection.replaceChildren();
      listSection.appendChild(errorState(error, () => void load()));
    }
  }

  await load();
}
