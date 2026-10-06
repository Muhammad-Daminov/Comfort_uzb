import * as cartState from "../state/cart";
import { createOrder, type CheckoutLine } from "../api/orders";
import { ApiError } from "../api/client";
import { formatSom } from "../components/price";
import { skeletonList } from "../components/loading";
import { emptyState } from "../components/empty-state";
import { errorState } from "../components/error-state";
import { setBackButton, setMainButton, hideMainButton, setMainButtonBusy } from "../telegram";
import { navigate } from "../router";
import { uz } from "../locale";
import { uuid } from "../uuid";

interface PriceMismatchDetail {
  lines: { variant_id: number; expected_unit_price: number }[];
}

export async function render(container: HTMLElement): Promise<void> {
  setBackButton(() => navigate("/cart"));

  const header = document.createElement("h2");
  header.textContent = "Buyurtma";
  container.appendChild(header);

  const summarySection = document.createElement("div");
  container.appendChild(summarySection);
  summarySection.appendChild(skeletonList(2, 40));

  const messageSection = document.createElement("div");
  container.appendChild(messageSection);

  let lines: CheckoutLine[] = [];
  let productNames: Record<number, string> = {};

  function renderSummaryFromLines(): void {
    summarySection.innerHTML = "";
    if (lines.length === 0) {
      summarySection.appendChild(emptyState(uz.emptyCart, undefined, "cart"));
      return;
    }
    let total = 0;
    for (const line of lines) {
      const unitPrice = line.client_unit_price ?? 0;
      total += unitPrice * line.quantity;
      const row = document.createElement("div");
      row.textContent = `${productNames[line.variant_id] ?? line.variant_id} × ${line.quantity} — ${formatSom(unitPrice * line.quantity)}`;
      summarySection.appendChild(row);
    }
    const totalRow = document.createElement("div");
    totalRow.style.fontWeight = "600";
    totalRow.style.marginTop = "8px";
    totalRow.textContent = `Jami: ${formatSom(total)}`;
    summarySection.appendChild(totalRow);
  }

  async function loadSummary(): Promise<void> {
    const items = await cartState.loadCart();
    // `current_price`, never `price`: the backend compares against the
    // §7.2-resolved price, so the base price 409'd on every discounted item.
    lines = items.map((item) => ({
      variant_id: item.variant_id,
      quantity: item.quantity,
      client_unit_price: cartState.unitPrice(item),
    }));
    idempotencyKey = uuid();
    productNames = Object.fromEntries(items.map((item) => [item.variant_id, item.product_name]));

    renderSummaryFromLines();

    if (items.length === 0) {
      hideMainButton();
      return;
    }

    setMainButton(uz.checkout, () => void submit());
  }

  // One key per *attempt body* (ADR-7): a retry after a timeout replays the
  // same request instead of creating a second order, and a double tap is
  // blocked while the first request is in flight. The key only changes
  // when the lines change (a price correction below).
  let idempotencyKey = uuid();
  let inFlight = false;

  async function submit(): Promise<void> {
    if (inFlight) return;
    inFlight = true;
    setMainButtonBusy(true);
    messageSection.innerHTML = "";

    try {
      const order = await createOrder(lines, idempotencyKey);
      navigate(`/order/${order.id}`);
    } catch (error) {
      if (error instanceof ApiError && error.code === "PRICE_MISMATCH") {
        idempotencyKey = uuid(); // the corrected lines are a new request
        // §7.3: backend rejected the client-believed price — show the
        // corrected price and let the user confirm before retrying, never
        // silently resubmit the old price.
        const details = error.details as PriceMismatchDetail;
        for (const mismatchedLine of details.lines) {
          const line = lines.find((l) => l.variant_id === mismatchedLine.variant_id);
          if (line) line.client_unit_price = mismatchedLine.expected_unit_price;
        }
        const notice = document.createElement("div");
        notice.className = "error-text";
        notice.textContent = uz.priceMismatch;
        messageSection.appendChild(notice);
        renderSummaryFromLines(); // re-render with the corrected prices already patched into `lines` — does NOT re-fetch the cart, which would discard the correction
        return;
      }

      if (error instanceof ApiError && error.code === "INSUFFICIENT_STOCK") {
        messageSection.appendChild(errorState(error));
        const backToCart = document.createElement("button");
        backToCart.className = "button-primary";
        backToCart.textContent = "Savatga qaytish";
        backToCart.addEventListener("click", () => navigate("/cart"));
        messageSection.appendChild(backToCart);
        return;
      }

      messageSection.appendChild(errorState(error, () => void submit()));
    } finally {
      inFlight = false;
      setMainButtonBusy(false);
    }
  }

  try {
    await loadSummary();
  } catch (error) {
    summarySection.appendChild(errorState(error, () => void loadSummary()));
  }
}
