import { getOrder } from "../api/orders";
import { submitPayment } from "../api/payments";
import { formatSom } from "../components/price";
import { skeletonList } from "../components/loading";
import { errorState } from "../components/error-state";
import { setBackButton, setMainButton, setMainButtonBusy } from "../telegram";
import { navigate } from "../router";
import { uz } from "../locale";
import { uuid } from "../uuid";

export async function render(container: HTMLElement, params: Record<string, string>): Promise<void> {
  container.replaceChildren(); // retry re-renders into the same container — never stack a second copy
  const orderId = Number(params.orderId);
  setBackButton(() => navigate(`/order/${orderId}`));

  const header = document.createElement("h2");
  header.textContent = "To'lov";
  container.appendChild(header);

  const infoSection = document.createElement("div");
  container.appendChild(infoSection);
  infoSection.appendChild(skeletonList(1, 40));

  const messageSection = document.createElement("div");
  container.appendChild(messageSection);

  try {
    const order = await getOrder(orderId);
    infoSection.innerHTML = "";
    infoSection.textContent = `To'lash kerak: ${formatSom(order.remaining_amount)}`;
    const instructions = document.createElement("p");
    instructions.className = "hint";
    instructions.textContent = "Bank kartasiga o'tkazma qiling, so'ng chekni yuklang.";
    container.insertBefore(instructions, messageSection);
  } catch (error) {
    infoSection.innerHTML = "";
    infoSection.appendChild(errorState(error, () => void render(container, params)));
    return;
  }

  setMainButton(uz.payNow, () => void handleSubmit());

  // Same key for every attempt on this screen (ADR-7): a retry after a
  // timeout replays, a double tap is ignored while the first is in flight.
  const idempotencyKey = uuid();
  let inFlight = false;

  async function handleSubmit(): Promise<void> {
    if (inFlight) return;
    inFlight = true;
    setMainButtonBusy(true);
    messageSection.innerHTML = "";
    try {
      const payment = await submitPayment(orderId, idempotencyKey);
      navigate(`/receipt/${payment.id}`);
    } catch (error) {
      messageSection.appendChild(errorState(error, () => void handleSubmit()));
    } finally {
      inFlight = false;
      setMainButtonBusy(false);
    }
  }
}
