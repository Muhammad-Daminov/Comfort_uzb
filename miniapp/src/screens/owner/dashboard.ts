import { getDashboard } from "../../api/owner";
import { formatSom } from "../../components/price";
import { skeletonList } from "../../components/loading";
import { errorState } from "../../components/error-state";
import { icon } from "../../components/icons";
import { aiAssistantCard } from "../../components/ai-assistant-card";
import { setBackButton } from "../../telegram";
import { navigate } from "../../router";

export async function render(container: HTMLElement): Promise<void> {
  container.replaceChildren(); // retry re-renders into the same container — never stack a second copy
  setBackButton(() => navigate("/home"));

  const header = document.createElement("h1");
  header.className = "screen-title";
  header.textContent = "Boshqaruv";
  container.appendChild(header);

  container.appendChild(aiAssistantCard());

  const nav = document.createElement("div");
  nav.className = "list mb-16";
  for (const [label, path, iconName] of [
    ["Moliya", "/owner/finance", "box"],
    ["Analitika", "/owner/analytics", "grid"],
    ["Adminlar", "/owner/admins", "shield"],
    ["Chegirmalar", "/owner/discounts", "percent"],
    ["Audit", "/owner/audit", "check"],
    ["Sozlamalar", "/owner/settings", "user"],
  ] as const) {
    const row = document.createElement("button");
    row.type = "button";
    row.className = "list-item";
    row.addEventListener("click", () => navigate(path));
    row.appendChild(icon(iconName, 18));
    const text = document.createElement("span");
    text.className = "grow list-title";
    text.textContent = label;
    row.appendChild(text);
    row.appendChild(icon("chevron-right", 16));
    nav.appendChild(row);
  }
  container.appendChild(nav);

  const body = document.createElement("div");
  container.appendChild(body);
  body.appendChild(skeletonList(3, 60));

  try {
    const summary = await getDashboard();
    body.innerHTML = "";

    const statGrid = document.createElement("div");
    statGrid.className = "stat-grid mb-16";

    const revenueStat = document.createElement("div");
    revenueStat.className = "stat";
    const revenueValue = document.createElement("div");
    revenueValue.className = "stat-value num";
    revenueValue.textContent = formatSom(summary.total_revenue);
    revenueStat.appendChild(revenueValue);
    const revenueLabel = document.createElement("div");
    revenueLabel.className = "stat-label";
    revenueLabel.textContent = "Jami daromad";
    revenueStat.appendChild(revenueLabel);
    statGrid.appendChild(revenueStat);

    const productsStat = document.createElement("div");
    productsStat.className = "stat";
    const productsValue = document.createElement("div");
    productsValue.className = "stat-value num";
    productsValue.textContent = `${summary.active_product_count}/${summary.product_count}`;
    productsStat.appendChild(productsValue);
    const productsLabel = document.createElement("div");
    productsLabel.className = "stat-label";
    productsLabel.textContent = "Faol / jami mahsulot";
    productsStat.appendChild(productsLabel);
    statGrid.appendChild(productsStat);

    body.appendChild(statGrid);

    const statusCard = document.createElement("div");
    statusCard.className = "card mb-12";
    const statusTitle = document.createElement("div");
    statusTitle.className = "section-title";
    statusTitle.style.margin = "0 0 8px";
    statusTitle.textContent = "Buyurtmalar holati bo'yicha";
    statusCard.appendChild(statusTitle);
    const entries = Object.entries(summary.order_counts_by_status);
    if (entries.length === 0) {
      const empty = document.createElement("div");
      empty.className = "hint";
      empty.textContent = "Hali buyurtma yo'q.";
      statusCard.appendChild(empty);
    } else {
      for (const [status, count] of entries) {
        const row = document.createElement("div");
        row.className = "row-between";
        row.style.padding = "4px 0";
        const label = document.createElement("span");
        label.className = "t-body";
        label.textContent = status;
        row.appendChild(label);
        const value = document.createElement("span");
        value.className = "t-label num";
        value.textContent = String(count);
        row.appendChild(value);
        statusCard.appendChild(row);
      }
    }
    body.appendChild(statusCard);

    if (summary.low_stock_variants.length > 0) {
      const lowStockCard = document.createElement("div");
      lowStockCard.className = "card";
      const title = document.createElement("div");
      title.className = "t-label";
      title.style.color = "var(--danger)";
      title.style.marginBottom = "8px";
      title.textContent = `Kam qolgan (≤${summary.low_stock_threshold})`;
      lowStockCard.appendChild(title);
      for (const variant of summary.low_stock_variants) {
        const row = document.createElement("div");
        row.className = "row-between";
        row.style.padding = "4px 0";
        const sku = document.createElement("span");
        sku.className = "t-body num";
        sku.textContent = variant.sku;
        row.appendChild(sku);
        const available = document.createElement("span");
        available.className = "badge badge-warn";
        available.textContent = `${variant.available} dona`;
        row.appendChild(available);
        lowStockCard.appendChild(row);
      }
      body.appendChild(lowStockCard);
    }
  } catch (error) {
    body.innerHTML = "";
    body.appendChild(errorState(error, () => void render(container)));
  }
}
