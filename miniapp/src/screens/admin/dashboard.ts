import { adminListOrders, adminListPayments } from "../../api/admin";
import { errorState } from "../../components/error-state";
import { skeletonList } from "../../components/loading";
import { icon } from "../../components/icons";
import { aiAssistantCard } from "../../components/ai-assistant-card";
import { setBackButton } from "../../telegram";
import { navigate } from "../../router";
import { isOwnerRole } from "../../state/session";

/** Minimal operational counts — ADMIN has no finance.view/analytics.view
 * (§3), so this is deliberately not a metrics dashboard, just quick links
 * into what needs attention. No new backend endpoint: composed from the
 * two existing admin list endpoints. */
export async function render(container: HTMLElement): Promise<void> {
  container.replaceChildren();
  setBackButton(() => navigate("/home"));

  const header = document.createElement("h1");
  header.className = "screen-title";
  header.textContent = "Admin panel";
  container.appendChild(header);

  container.appendChild(aiAssistantCard());

  const statsSection = document.createElement("div");
  container.appendChild(statsSection);
  statsSection.appendChild(skeletonList(2, 70));

  try {
    const [pendingOrders, pendingPayments] = await Promise.all([
      adminListOrders("UNDER_REVIEW"),
      adminListPayments("PENDING"),
    ]);

    statsSection.innerHTML = "";

    const statGrid = document.createElement("div");
    statGrid.className = "stat-grid mb-16";

    const ordersStat = document.createElement("button");
    ordersStat.type = "button";
    ordersStat.className = "stat card-tap";
    ordersStat.style.textAlign = "left";
    ordersStat.addEventListener("click", () => navigate("/admin/orders"));
    const ordersValue = document.createElement("div");
    ordersValue.className = "stat-value num";
    ordersValue.textContent = String(pendingOrders.items.length);
    ordersStat.appendChild(ordersValue);
    const ordersLabel = document.createElement("div");
    ordersLabel.className = "stat-label";
    ordersLabel.textContent = "Ko'rib chiqilishi kerak";
    ordersStat.appendChild(ordersLabel);
    statGrid.appendChild(ordersStat);

    const paymentsStat = document.createElement("button");
    paymentsStat.type = "button";
    paymentsStat.className = "stat card-tap";
    paymentsStat.style.textAlign = "left";
    paymentsStat.addEventListener("click", () => navigate("/admin/payments"));
    const paymentsValue = document.createElement("div");
    paymentsValue.className = "stat-value num";
    paymentsValue.textContent = String(pendingPayments.items.length);
    paymentsStat.appendChild(paymentsValue);
    const paymentsLabel = document.createElement("div");
    paymentsLabel.className = "stat-label";
    paymentsLabel.textContent = "Kutilayotgan to'lovlar";
    paymentsStat.appendChild(paymentsLabel);
    statGrid.appendChild(paymentsStat);

    container.appendChild(statGrid);

    const nav = document.createElement("div");
    nav.className = "list";

    const links: Array<[string, string, Parameters<typeof icon>[0]]> = [
      ["Mahsulotlar", "/admin/products", "box"],
      ["Stok", "/admin/stock", "grid"],
    ];
    for (const [label, path, iconName] of links) {
      nav.appendChild(navRow(label, iconName, () => navigate(path)));
    }
    if (isOwnerRole()) {
      nav.appendChild(navRow("Boshqaruv (Owner)", "crown", () => navigate("/owner")));
    }
    container.appendChild(nav);
  } catch (error) {
    statsSection.innerHTML = "";
    statsSection.appendChild(errorState(error, () => void render(container)));
  }
}

function navRow(label: string, iconName: Parameters<typeof icon>[0], onClick: () => void): HTMLElement {
  const row = document.createElement("button");
  row.type = "button";
  row.className = "list-item";
  row.addEventListener("click", onClick);

  row.appendChild(icon(iconName, 18));

  const text = document.createElement("span");
  text.className = "grow list-title";
  text.textContent = label;
  row.appendChild(text);

  row.appendChild(icon("chevron-right", 16));
  return row;
}
