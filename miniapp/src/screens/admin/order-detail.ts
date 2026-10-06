import { getOrder } from "../../api/orders";
import {
  adminConfirmOrder,
  adminCancelOrder,
  adminApproveCancellationRequest,
  adminDenyCancellationRequest,
  adminRecordRefund,
  adminCompleteRefund,
} from "../../api/admin";
import { formatSom } from "../../components/price";
import { skeletonList } from "../../components/loading";
import { errorState } from "../../components/error-state";
import { setBackButton, setMainButton, hideMainButton, setMainButtonBusy } from "../../telegram";
import { navigate } from "../../router";
import { uuid } from "../../uuid";

// Visual-only migration to the premium design system (§P3B-1) — same
// confirm/cancel/cancellation-request/refund calls, same idempotency-key
// discipline (ADR-7), same window.prompt-based destructive confirmations.

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

function sectionHeading(text: string): HTMLElement {
  const heading = document.createElement("div");
  heading.className = "section-title";
  heading.textContent = text;
  return heading;
}

export async function render(container: HTMLElement, params: Record<string, string>): Promise<void> {
  setBackButton(() => navigate("/admin/orders"));
  const orderId = Number(params.id);

  container.replaceChildren(skeletonList(1, 160));

  async function load(): Promise<void> {
    container.replaceChildren();
    let order;
    try {
      order = await getOrder(orderId);
    } catch (error) {
      container.appendChild(errorState(error, () => void load()));
      return;
    }

    const header = document.createElement("h1");
    header.className = "screen-title";
    header.textContent = `Buyurtma ${order.order_number}`;
    container.appendChild(header);

    const statusCard = document.createElement("div");
    statusCard.className = "card mb-16";
    const statusRow = document.createElement("div");
    statusRow.className = "row-between mb-8";
    const statusBadge = document.createElement("span");
    statusBadge.className = ORDER_STATUS_BADGE[order.status] ?? "badge";
    statusBadge.textContent = ORDER_STATUS_LABEL[order.status] ?? order.status;
    statusRow.appendChild(statusBadge);
    statusCard.appendChild(statusRow);

    const total = document.createElement("div");
    total.className = "row-between";
    const totalLabel = document.createElement("span");
    totalLabel.className = "t-body";
    totalLabel.textContent = "Jami";
    const totalValue = document.createElement("span");
    totalValue.className = "price-now";
    totalValue.textContent = formatSom(order.total_amount);
    total.appendChild(totalLabel);
    total.appendChild(totalValue);
    statusCard.appendChild(total);

    const paid = document.createElement("div");
    paid.className = "row-between mt-8";
    const paidLabel = document.createElement("span");
    paidLabel.className = "hint";
    paidLabel.textContent = "To'langan";
    const paidValue = document.createElement("span");
    paidValue.className = "hint num";
    paidValue.textContent = formatSom(order.paid_amount);
    paid.appendChild(paidLabel);
    paid.appendChild(paidValue);
    statusCard.appendChild(paid);

    container.appendChild(statusCard);

    const messageSection = document.createElement("div");
    container.appendChild(messageSection);

    const pendingRequest = (order.cancellation_requests ?? []).find((r) => r.status === "PENDING");
    if (pendingRequest) {
      container.appendChild(sectionHeading("Bekor qilish so'rovi"));
      const requestCard = document.createElement("div");
      requestCard.className = "card mb-16";
      const requestText = document.createElement("div");
      requestText.className = "t-body mb-12";
      requestText.textContent = pendingRequest.reason;
      requestCard.appendChild(requestText);

      const requestActions = document.createElement("div");
      requestActions.style.display = "flex";
      requestActions.style.gap = "8px";

      const approveButton = document.createElement("button");
      approveButton.type = "button";
      approveButton.className = "btn btn-pri btn-sm grow";
      approveButton.textContent = "So'rovni tasdiqlash";
      approveButton.addEventListener("click", () => void handleDecideCancellation(true));
      requestActions.appendChild(approveButton);

      const denyButton = document.createElement("button");
      denyButton.type = "button";
      denyButton.className = "btn btn-dang btn-sm grow";
      denyButton.textContent = "So'rovni rad etish";
      denyButton.addEventListener("click", () => void handleDecideCancellation(false));
      requestActions.appendChild(denyButton);

      requestCard.appendChild(requestActions);
      container.appendChild(requestCard);
    }

    if (order.status === "CANCELLED" && order.paid_amount > 0) {
      const alreadyRefunded = (order.refunds ?? []).reduce(
        (sum, r) => (r.status === "COMPLETED" ? sum + r.amount : sum),
        0,
      );
      container.appendChild(sectionHeading("Qaytarish"));

      if (alreadyRefunded < order.paid_amount) {
        const refundButton = document.createElement("button");
        refundButton.type = "button";
        refundButton.className = "btn btn-pri btn-block mb-12";
        refundButton.textContent = "Qaytarishni qayd etish";
        refundButton.addEventListener("click", () => void handleRecordRefund());
        container.appendChild(refundButton);
      }
      for (const refund of order.refunds ?? []) {
        const refundCard = document.createElement("div");
        refundCard.className = "card mb-12";
        const refundRow = document.createElement("div");
        refundRow.className = "row-between";
        const refundInfo = document.createElement("span");
        refundInfo.className = "t-body";
        refundInfo.textContent = `${refund.method} — ${formatSom(refund.amount)}`;
        const refundBadge = document.createElement("span");
        refundBadge.className = refund.status === "COMPLETED" ? "badge badge-ok" : "badge badge-warn";
        refundBadge.textContent = refund.status;
        refundRow.appendChild(refundInfo);
        refundRow.appendChild(refundBadge);
        refundCard.appendChild(refundRow);
        if (refund.status === "PENDING") {
          const completeButton = document.createElement("button");
          completeButton.type = "button";
          completeButton.className = "btn btn-sec btn-sm btn-block mt-12";
          completeButton.textContent = "Bajarildi deb belgilash";
          completeButton.addEventListener("click", () => void handleCompleteRefund(refund.id));
          refundCard.appendChild(completeButton);
        }
        container.appendChild(refundCard);
      }
    }

    if (order.status === "UNDER_REVIEW") {
      setMainButton("Tasdiqlash", () => void handleConfirm());
    } else {
      hideMainButton();
    }

    if (["UNDER_REVIEW", "PAYMENT_SUBMITTED", "AWAITING_PAYMENT", "CREATED"].includes(order.status)) {
      const cancelButton = document.createElement("button");
      cancelButton.type = "button";
      cancelButton.className = "btn btn-dang btn-block mt-12";
      cancelButton.textContent = "Bekor qilish";
      cancelButton.addEventListener("click", () => void handleCancel());
      container.appendChild(cancelButton);
    }

    // One key per screen load (ADR-7): a retry replays instead of racing a
    // second confirm; a double tap is ignored while one is in flight.
    const confirmKey = uuid();
    let inFlight = false;

    async function handleConfirm(): Promise<void> {
      if (inFlight) return;
      inFlight = true;
      setMainButtonBusy(true);
      messageSection.replaceChildren();
      try {
        await adminConfirmOrder(order!.id, confirmKey);
        await load();
      } catch (error) {
        messageSection.appendChild(errorState(error, () => void handleConfirm()));
      } finally {
        inFlight = false;
        setMainButtonBusy(false);
      }
    }

    async function handleCancel(): Promise<void> {
      const reason = window.prompt("Bekor qilish sababi (kamida 10 belgi):");
      if (!reason || reason.trim().length < 10) return;
      messageSection.replaceChildren();
      try {
        await adminCancelOrder(order!.id, reason.trim(), uuid());
        await load();
      } catch (error) {
        messageSection.appendChild(errorState(error, () => void handleCancel()));
      }
    }

    async function handleDecideCancellation(approve: boolean): Promise<void> {
      if (!pendingRequest) return;
      messageSection.replaceChildren();
      try {
        if (approve) {
          await adminApproveCancellationRequest(pendingRequest.id);
        } else {
          const note = window.prompt("Rad etish sababi (ixtiyoriy):") ?? undefined;
          await adminDenyCancellationRequest(pendingRequest.id, note);
        }
        await load();
      } catch (error) {
        messageSection.appendChild(errorState(error, () => void handleDecideCancellation(approve)));
      }
    }

    async function handleRecordRefund(): Promise<void> {
      const amountText = window.prompt(`Qaytarish summasi (so'mda, maks. ${formatSom(order!.paid_amount)}):`);
      if (!amountText) return;
      const amount = Number(amountText.replace(/\D/g, ""));
      if (!Number.isFinite(amount) || amount <= 0) return;
      const method = window.confirm("Naqd pul orqalimi? (OK = naqd, Bekor = karta)") ? "CASH" : "CARD";
      const reason = window.prompt("Qaytarish sababi (kamida 10 belgi):");
      if (!reason || reason.trim().length < 10) return;
      messageSection.replaceChildren();
      try {
        await adminRecordRefund(order!.id, amount, method, reason.trim());
        await load();
      } catch (error) {
        messageSection.appendChild(errorState(error, () => void handleRecordRefund()));
      }
    }

    async function handleCompleteRefund(refundId: number): Promise<void> {
      messageSection.replaceChildren();
      try {
        await adminCompleteRefund(refundId);
        await load();
      } catch (error) {
        messageSection.appendChild(errorState(error, () => void handleCompleteRefund(refundId)));
      }
    }
  }

  await load();
}
