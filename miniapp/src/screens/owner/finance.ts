import { getFinance } from "../../api/owner";
import { formatSom } from "../../components/price";
import { skeletonList } from "../../components/loading";
import { errorState } from "../../components/error-state";
import { setBackButton } from "../../telegram";
import { navigate } from "../../router";

// Visual-only migration to the premium design system (§P3B-1) — same
// getFinance call/date-range params, same breakdown/payments data, same
// "hidden before review" warning. OWNER-only data, unchanged: this screen
// is reached only via the /owner/finance route, itself gated server-side
// by `finance.view` (ADMIN does not hold that permission — see
// app/domains/owner/router.py) — the frontend route existing here is not
// what enforces that, the backend permission check is.

function field(labelText: string, control: HTMLElement): HTMLElement {
  const wrapper = document.createElement("div");
  wrapper.className = "field";
  const label = document.createElement("label");
  label.className = "field-label";
  label.textContent = labelText;
  wrapper.appendChild(label);
  wrapper.appendChild(control);
  return wrapper;
}

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
  container.replaceChildren();
  setBackButton(() => navigate("/owner"));

  const header = document.createElement("h1");
  header.className = "screen-title";
  header.textContent = "Moliya";
  container.appendChild(header);

  const today = new Date();
  const monthAgo = new Date(today);
  monthAgo.setDate(monthAgo.getDate() - 30);

  const fromInput = document.createElement("input");
  fromInput.type = "date";
  fromInput.value = isoDate(monthAgo);
  const toInput = document.createElement("input");
  toInput.type = "date";
  toInput.value = isoDate(today);
  const filterButton = document.createElement("button");
  filterButton.type = "button";
  filterButton.className = "btn btn-pri btn-block mb-16";
  filterButton.textContent = "Ko'rish";

  const filterBar = document.createElement("div");
  filterBar.className = "mb-16";
  filterBar.appendChild(field("Boshlanish sanasi", fromInput));
  filterBar.appendChild(field("Tugash sanasi", toInput));
  filterBar.appendChild(filterButton);
  container.appendChild(filterBar);

  const body = document.createElement("div");
  container.appendChild(body);

  async function load(): Promise<void> {
    body.replaceChildren();
    body.appendChild(skeletonList(3, 70));
    try {
      const finance = await getFinance(fromInput.value, toInput.value);
      body.replaceChildren();

      const summary = document.createElement("div");
      summary.className = "stat-grid mb-16";

      const revenueStat = document.createElement("div");
      revenueStat.className = "stat";
      const revenueValue = document.createElement("div");
      revenueValue.className = "stat-value num";
      revenueValue.textContent = formatSom(finance.revenue);
      revenueStat.appendChild(revenueValue);
      const revenueLabel = document.createElement("div");
      revenueLabel.className = "stat-label";
      revenueLabel.textContent = "Daromad";
      revenueStat.appendChild(revenueLabel);
      summary.appendChild(revenueStat);

      const ordersStat = document.createElement("div");
      ordersStat.className = "stat";
      const ordersValue = document.createElement("div");
      ordersValue.className = "stat-value num";
      ordersValue.textContent = String(finance.order_count);
      ordersStat.appendChild(ordersValue);
      const ordersLabel = document.createElement("div");
      ordersLabel.className = "stat-label";
      ordersLabel.textContent = "Buyurtmalar";
      ordersStat.appendChild(ordersLabel);
      summary.appendChild(ordersStat);

      body.appendChild(summary);

      if (finance.payment_status_breakdown.length > 0) {
        const breakdownCard = document.createElement("div");
        breakdownCard.className = "card mb-16";
        for (const breakdown of finance.payment_status_breakdown) {
          const row = document.createElement("div");
          row.className = "row-between";
          row.style.padding = "4px 0";
          const label = document.createElement("span");
          label.className = "t-body";
          label.textContent = `${breakdown.status}: ${breakdown.count} ta`;
          row.appendChild(label);
          const value = document.createElement("span");
          value.className = "t-label num";
          value.textContent = formatSom(breakdown.total_amount);
          row.appendChild(value);
          breakdownCard.appendChild(row);
        }
        body.appendChild(breakdownCard);
      }

      body.appendChild(sectionHeading("To'lovlar"));

      for (const payment of finance.payments) {
        const row = document.createElement("div");
        row.className = "card mb-8";
        const top = document.createElement("div");
        top.className = "row-between";
        const label = document.createElement("span");
        label.className = "t-body num";
        label.textContent = `#${payment.payment_id} — Buyurtma #${payment.order_id}`;
        top.appendChild(label);
        const badge = document.createElement("span");
        badge.className = payment.status === "APPROVED" ? "badge badge-ok" : "badge";
        badge.textContent = payment.status;
        top.appendChild(badge);
        row.appendChild(top);

        const amount = document.createElement("div");
        amount.className = "price-now mt-8";
        amount.textContent = formatSom(payment.amount);
        row.appendChild(amount);

        if (payment.hidden_before_review) {
          const warning = document.createElement("div");
          warning.className = "hint mt-8";
          warning.style.color = "var(--danger)";
          warning.textContent = "tekshiruvdan oldin yashirilgan";
          row.appendChild(warning);
        }
        body.appendChild(row);
      }
    } catch (error) {
      body.replaceChildren();
      body.appendChild(errorState(error, () => void load()));
    }
  }

  filterButton.addEventListener("click", () => void load());
  await load();
}
