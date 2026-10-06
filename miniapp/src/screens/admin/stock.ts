import { searchProducts, getProduct } from "../../api/catalog";
import { adminAdjustInventory } from "../../api/admin";
import { emptyState } from "../../components/empty-state";
import { errorState } from "../../components/error-state";
import { icon } from "../../components/icons";
import { setBackButton } from "../../telegram";
import { navigate } from "../../router";
import { uuid } from "../../uuid";

// Visual-only migration to the premium design system (§P3B-1) — same
// search/debounce/adjust-stock endpoint calls as before.

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

export function render(container: HTMLElement): void {
  container.replaceChildren();
  setBackButton(() => navigate("/admin"));

  const header = document.createElement("h1");
  header.className = "screen-title";
  header.textContent = "Stok";
  container.appendChild(header);

  const searchInput = document.createElement("input");
  searchInput.type = "search";
  searchInput.placeholder = "Mahsulot qidirish...";
  container.appendChild(field("Qidiruv", searchInput));

  const resultsSection = document.createElement("div");
  container.appendChild(resultsSection);

  let debounceHandle: ReturnType<typeof setTimeout> | null = null;
  searchInput.addEventListener("input", () => {
    if (debounceHandle) clearTimeout(debounceHandle);
    const query = searchInput.value.trim();
    if (!query) {
      resultsSection.replaceChildren();
      return;
    }
    debounceHandle = setTimeout(() => {
      searchProducts(query)
        .then((response) => {
          resultsSection.replaceChildren();
          if (response.items.length === 0) {
            resultsSection.appendChild(emptyState("Hech narsa topilmadi.", undefined, "search"));
            return;
          }
          for (const product of response.items) {
            const row = document.createElement("button");
            row.type = "button";
            row.className = "card card-tap mb-8";
            row.style.width = "100%";
            row.style.textAlign = "left";
            row.style.display = "flex";
            row.style.justifyContent = "space-between";
            row.style.alignItems = "center";
            const name = document.createElement("span");
            name.className = "list-title";
            name.textContent = product.name;
            row.appendChild(name);
            row.appendChild(icon("chevron-right", 16));
            row.addEventListener("click", () => void showVariants(product.id));
            resultsSection.appendChild(row);
          }
        })
        .catch((error: unknown) => {
          resultsSection.replaceChildren();
          resultsSection.appendChild(errorState(error));
        });
    }, 300);
  });

  async function showVariants(productId: number): Promise<void> {
    resultsSection.replaceChildren();
    let detail;
    try {
      detail = await getProduct(productId);
    } catch (error) {
      resultsSection.appendChild(errorState(error, () => void showVariants(productId)));
      return;
    }
    for (const variant of detail.variants) {
      const row = document.createElement("div");
      row.className = "card mb-12";

      const info = document.createElement("div");
      info.className = "mb-12";
      const sku = document.createElement("div");
      sku.className = "list-title num";
      sku.textContent = variant.sku;
      info.appendChild(sku);
      const stockLine = document.createElement("div");
      stockLine.className = "hint";
      stockLine.textContent = `Stok: ${variant.stock_on_hand} (band: ${variant.stock_reserved})`;
      info.appendChild(stockLine);
      row.appendChild(info);

      const adjustInput = document.createElement("input");
      adjustInput.type = "number";
      adjustInput.placeholder = "+/- miqdor";
      row.appendChild(field("Miqdor o'zgarishi", adjustInput));

      const reasonInput = document.createElement("input");
      reasonInput.placeholder = "Sabab";
      row.appendChild(field("Sabab", reasonInput));

      const messageSection = document.createElement("div");

      const submitButton = document.createElement("button");
      submitButton.type = "button";
      submitButton.className = "btn btn-pri btn-block";
      submitButton.textContent = "Saqlash";
      submitButton.addEventListener("click", () => {
        messageSection.replaceChildren();
        const change = Number(adjustInput.value);
        if (!change || !reasonInput.value.trim()) {
          messageSection.appendChild(errorState(new Error("Miqdor va sabab kiritilishi shart")));
          return;
        }
        submitButton.disabled = true;
        void adminAdjustInventory(variant.id, change, reasonInput.value.trim(), uuid())
          .then(() => void showVariants(productId))
          .catch((error: unknown) => {
            submitButton.disabled = false;
            messageSection.appendChild(errorState(error));
          });
      });
      row.appendChild(submitButton);
      row.appendChild(messageSection);

      resultsSection.appendChild(row);
    }
  }
}
