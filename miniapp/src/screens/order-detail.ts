import { getOrder, cancelOrder, requestCancellation, type OrderResponse } from "../api/orders";
import { formatSom } from "../components/price";
import { skeletonList } from "../components/loading";
import { errorState } from "../components/error-state";
import { setBackButton, setMainButton, hideMainButton } from "../telegram";
import { navigate } from "../router";
import { uz } from "../locale";

const STATUS_LABEL_UZ: Record<string, string> = {
  CREATED: "Yaratildi",
  AWAITING_PAYMENT: "To'lov kutilmoqda",
  PAYMENT_SUBMITTED: "To'lov yuborildi",
  UNDER_REVIEW: "Ko'rib chiqilmoqda",
  CONFIRMED: "Tasdiqlandi",
  REJECTED: "Rad etildi",
  CANCELLED: "Bekor qilindi",
  EXPIRED: "Muddati o'tdi",
};

// REJECTED -> CANCELLED is the only exit the TZ allows from REJECTED (§8.1).
const CANCELLABLE_STATUSES = new Set(["CREATED", "AWAITING_PAYMENT", "PAYMENT_SUBMITTED", "UNDER_REVIEW", "REJECTED"]);

export async function render(container: HTMLElement, params: Record<string, string>): Promise<void> {
  setBackButton(() => navigate("/home"));
  const orderId = Number(params.id);

  container.appendChild(skeletonList(1, 160));

  async function load(): Promise<void> {
    container.innerHTML = "";
    let order: OrderResponse;
    try {
      order = await getOrder(orderId);
    } catch (error) {
      container.appendChild(errorState(error, () => void load()));
      return;
    }

    const header = document.createElement("h2");
    header.textContent = `Buyurtma ${order.order_number}`;
    container.appendChild(header);

    const status = document.createElement("div");
    status.className = "card";
    status.textContent = STATUS_LABEL_UZ[order.status] ?? order.status;
    container.appendChild(status);

    const total = document.createElement("div");
    total.style.margin = "12px 0";
    total.textContent = `Jami: ${formatSom(order.total_amount)}`;
    container.appendChild(total);

    const paid = document.createElement("div");
    paid.className = "hint";
    paid.textContent = `To'langan: ${formatSom(order.paid_amount)} / Qoldiq: ${formatSom(order.remaining_amount)}`;
    container.appendChild(paid);

    // ADR-017: a CONFIRMED order with a still-PENDING cancellation request
    // shows its status instead of an actionable button; refunds are shown
    // whenever any exist, regardless of order status.
    const openRequest = (order.cancellation_requests ?? []).find((r) => r.status === "PENDING");
    if (order.cancellation_requests && order.cancellation_requests.length > 0) {
      const latest = order.cancellation_requests[0];
      const requestStatus = document.createElement("div");
      requestStatus.className = "card mt-12";
      requestStatus.textContent =
        latest.status === "PENDING"
          ? uz.cancellationStatusPending
          : latest.status === "APPROVED"
            ? uz.cancellationStatusApproved
            : uz.cancellationStatusDenied;
      container.appendChild(requestStatus);
    }
    if (order.refunds && order.refunds.length > 0) {
      for (const refund of order.refunds) {
        const refundStatus = document.createElement("div");
        refundStatus.className = "card mt-12";
        const label =
          refund.status === "PENDING"
            ? uz.refundStatusPending
            : refund.status === "COMPLETED"
              ? uz.refundStatusCompleted
              : uz.refundStatusFailed;
        refundStatus.textContent = `${label}: ${formatSom(refund.amount)}`;
        container.appendChild(refundStatus);
      }
    }

    const messageSection = document.createElement("div");
    container.appendChild(messageSection);

    if (order.status === "CREATED" || order.status === "AWAITING_PAYMENT") {
      setMainButton(uz.payNow, () => navigate(`/payment/${order.id}`));
      // The state machine allows cancelling an unpaid order too — the
      // MainButton is taken by "pay", so cancel gets an inline button
      // (before this, an unpaid order could not be cancelled from the UI).
      const cancelButton = document.createElement("button");
      cancelButton.type = "button";
      cancelButton.className = "btn btn-block mt-12";
      cancelButton.textContent = uz.cancelOrder;
      cancelButton.addEventListener("click", () => void handleCancel());
      container.appendChild(cancelButton);
    } else if (CANCELLABLE_STATUSES.has(order.status)) {
      setMainButton(uz.cancelOrder, () => void handleCancel());
    } else if (order.status === "CONFIRMED" && !openRequest) {
      // §10 of the v2 brief: a paid customer cannot self-cancel; this is
      // the request-then-admin-decides path, not a direct cancel.
      setMainButton(uz.requestCancellation, () => void handleRequestCancellation());
    } else {
      hideMainButton();
    }

    async function handleCancel(): Promise<void> {
      const reason = window.prompt(uz.cancellationReasonPrompt);
      if (!reason || reason.trim().length < 10) return;
      messageSection.replaceChildren();
      try {
        await cancelOrder(order.id, reason.trim());
        await load();
      } catch (error) {
        messageSection.appendChild(errorState(error));
      }
    }

    async function handleRequestCancellation(): Promise<void> {
      const reason = window.prompt(uz.cancellationReasonPrompt);
      if (!reason || reason.trim().length < 10) return;
      messageSection.replaceChildren();
      try {
        await requestCancellation(order.id, reason.trim());
        messageSection.textContent = uz.cancellationRequestSent;
        await load();
      } catch (error) {
        messageSection.appendChild(errorState(error));
      }
    }
  }

  await load();
}
