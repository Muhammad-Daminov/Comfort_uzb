import { searchProducts } from "../api/catalog";
import { productCard } from "../components/product-card";
import { emptyState } from "../components/empty-state";
import { errorState } from "../components/error-state";
import { setBackButton } from "../telegram";
import { navigate } from "../router";
import { uz } from "../locale";

const DEBOUNCE_MS = 300;

export function render(container: HTMLElement): void {
  setBackButton(() => navigate("/catalog"));

  const header = document.createElement("h2");
  header.textContent = "Qidiruv";
  container.appendChild(header);

  const input = document.createElement("input");
  input.type = "search";
  input.placeholder = "Nom, brend, SKU...";
  input.style.width = "100%";
  input.style.padding = "10px";
  input.style.fontSize = "16px";
  container.appendChild(input);

  const resultsSection = document.createElement("div");
  resultsSection.style.marginTop = "12px";
  container.appendChild(resultsSection);

  let debounceHandle: ReturnType<typeof setTimeout> | null = null;
  let inFlightController: AbortController | null = null;

  input.addEventListener("input", () => {
    if (debounceHandle) clearTimeout(debounceHandle);
    const query = input.value.trim();

    if (query.length === 0) {
      resultsSection.innerHTML = "";
      return;
    }

    debounceHandle = setTimeout(() => {
      // Cancel any still-in-flight previous query — prevents a slow older
      // response from overwriting a newer one (stale-result race).
      inFlightController?.abort();
      const controller = new AbortController();
      inFlightController = controller;

      searchProducts(query, controller.signal)
        .then((response) => {
          if (controller.signal.aborted) return;
          resultsSection.innerHTML = "";
          if (response.items.length === 0) {
            resultsSection.appendChild(emptyState(uz.emptySearch, undefined, "search"));
            return;
          }
          for (const product of response.items) {
            resultsSection.appendChild(productCard(product));
          }
        })
        .catch((error: unknown) => {
          if (error instanceof DOMException && error.name === "AbortError") return;
          resultsSection.innerHTML = "";
          resultsSection.appendChild(errorState(error));
        });
    }, DEBOUNCE_MS);
  });
}
