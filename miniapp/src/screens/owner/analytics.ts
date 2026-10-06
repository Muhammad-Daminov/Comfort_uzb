import { getAnalytics } from "../../api/owner";
import { formatSom } from "../../components/price";
import { skeletonList } from "../../components/loading";
import { errorState } from "../../components/error-state";
import { setBackButton } from "../../telegram";
import { navigate } from "../../router";

// Visual-only migration to the premium design system (§P3B-1) — same
// getAnalytics call/date range (last 30 days), same data fields.

function sectionHeading(text: string): HTMLElement {
  const heading = document.createElement("div");
  heading.className = "section-title";
  heading.textContent = text;
  return heading;
}

function isoDate(date: Date): string {
  return date.toISOString().slice(0, 10);
}

export async function render(container: HTMLElement): Promise<void> {
  container.replaceChildren(); // retry re-renders into the same container — never stack a second copy
  setBackButton(() => navigate("/owner"));

  const header = document.createElement("h1");
  header.className = "screen-title";
  header.textContent = "Analitika";
  container.appendChild(header);

  const body = document.createElement("div");
  container.appendChild(body);
  body.appendChild(skeletonList(3, 70));

  const today = new Date();
  const monthAgo = new Date(today);
  monthAgo.setDate(monthAgo.getDate() - 30);

  try {
    const analytics = await getAnalytics(isoDate(monthAgo), isoDate(today));
    body.replaceChildren();

    body.appendChild(sectionHeading("Buyurtma holatlari"));
    const statusEntries = Object.entries(analytics.order_status_distribution);
    if (statusEntries.length === 0) {
      const empty = document.createElement("div");
      empty.className = "hint mb-16";
      empty.textContent = "Ma'lumot yo'q";
      body.appendChild(empty);
    } else {
      const statusCard = document.createElement("div");
      statusCard.className = "card mb-16";
      for (const [status, count] of statusEntries) {
        const row = document.createElement("div");
        row.className = "row-between";
        row.style.padding = "4px 0";
        const label = document.createElement("span");
        label.className = "t-body";
        label.textContent = status;
        row.appendChild(label);
        const value = document.createElement("span");
        value.className = "t-label num";
        value.textContent = `: ${count}`;
        row.appendChild(value);
        statusCard.appendChild(row);
      }
      body.appendChild(statusCard);
    }

    body.appendChild(sectionHeading("Ko'p sotilgan mahsulotlar"));
    if (analytics.best_selling_products.length === 0) {
      const empty = document.createElement("div");
      empty.className = "hint mb-16";
      empty.textContent = "Ma'lumot yo'q";
      body.appendChild(empty);
    } else {
      for (const product of analytics.best_selling_products) {
        const row = document.createElement("div");
        row.className = "card mb-8";
        const top = document.createElement("div");
        top.className = "row-between";
        const name = document.createElement("span");
        name.className = "t-body";
        name.textContent = `${product.product_name_snapshot} (${product.sku_snapshot})`;
        top.appendChild(name);
        const qty = document.createElement("span");
        qty.className = "hint";
        qty.textContent = `${product.total_quantity} dona`;
        top.appendChild(qty);
        row.appendChild(top);
        const revenue = document.createElement("div");
        revenue.className = "price-now mt-8";
        revenue.textContent = formatSom(product.total_revenue);
        row.appendChild(revenue);
        body.appendChild(row);
      }
    }

    body.appendChild(sectionHeading("Vaqt bo'yicha"));
    if (analytics.orders_over_time.length === 0) {
      const empty = document.createElement("div");
      empty.className = "hint";
      empty.textContent = "Ma'lumot yo'q";
      body.appendChild(empty);
    } else {
      const timeCard = document.createElement("div");
      timeCard.className = "card";
      for (const point of analytics.orders_over_time) {
        const row = document.createElement("div");
        row.className = "row-between";
        row.style.padding = "4px 0";
        const label = document.createElement("span");
        label.className = "hint num";
        label.textContent = point.day.slice(0, 10);
        row.appendChild(label);
        const value = document.createElement("span");
        value.className = "hint";
        value.textContent = `${point.order_count} buyurtma, ${formatSom(point.revenue)}`;
        row.appendChild(value);
        timeCard.appendChild(row);
      }
      body.appendChild(timeCard);
    }
  } catch (error) {
    body.replaceChildren();
    body.appendChild(errorState(error, () => void render(container)));
  }
}
