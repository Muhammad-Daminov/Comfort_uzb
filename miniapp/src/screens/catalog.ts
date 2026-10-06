import { listProducts, getFilters, type ProductListFilters, type FiltersResponse } from "../api/catalog";
import { productCard } from "../components/product-card";
import { skeletonList } from "../components/loading";
import { emptyState } from "../components/empty-state";
import { errorState } from "../components/error-state";
import { setBackButton } from "../telegram";
import { navigate } from "../router";
import { uz } from "../locale";

export async function render(container: HTMLElement): Promise<void> {
  setBackButton(() => navigate("/home"));

  const header = document.createElement("h2");
  header.textContent = "Katalog";
  container.appendChild(header);

  const searchButton = document.createElement("button");
  searchButton.className = "button-primary";
  searchButton.textContent = "Qidirish";
  searchButton.style.marginBottom = "12px";
  searchButton.addEventListener("click", () => navigate("/search"));
  container.appendChild(searchButton);

  const filterBar = document.createElement("div");
  filterBar.style.display = "flex";
  filterBar.style.gap = "8px";
  filterBar.style.marginBottom = "12px";
  filterBar.style.flexWrap = "wrap";
  container.appendChild(filterBar);

  const resultsSection = document.createElement("div");
  container.appendChild(resultsSection);

  const state: { filters: ProductListFilters; nextCursor: string | null } = { filters: { limit: 20 }, nextCursor: null };

  function renderFilterControls(filtersData: FiltersResponse): void {
    filterBar.innerHTML = "";

    const brandSelect = document.createElement("select");
    const anyBrandOption = document.createElement("option");
    anyBrandOption.value = "";
    anyBrandOption.textContent = "Barcha brendlar";
    brandSelect.appendChild(anyBrandOption);
    for (const brand of filtersData.brands) {
      const option = document.createElement("option");
      option.value = String(brand.id);
      option.textContent = brand.name;
      brandSelect.appendChild(option);
    }
    brandSelect.addEventListener("change", () => {
      state.filters.brand_id = brandSelect.value ? Number(brandSelect.value) : undefined;
      void loadResults(true);
    });
    filterBar.appendChild(brandSelect);

    const sortSelect = document.createElement("select");
    const sortOptions: { value: ProductListFilters["sort"]; label: string }[] = [
      { value: "newest", label: "Yangi" },
      { value: "price_asc", label: "Narx: arzon" },
      { value: "price_desc", label: "Narx: qimmat" },
      { value: "popular", label: "Mashhur" },
    ];
    for (const option of sortOptions) {
      const el = document.createElement("option");
      el.value = option.value as string;
      el.textContent = option.label;
      sortSelect.appendChild(el);
    }
    sortSelect.addEventListener("change", () => {
      state.filters.sort = sortSelect.value as ProductListFilters["sort"];
      void loadResults(true);
    });
    filterBar.appendChild(sortSelect);

    const inStockLabel = document.createElement("label");
    inStockLabel.style.display = "flex";
    inStockLabel.style.alignItems = "center";
    inStockLabel.style.gap = "4px";
    const inStockCheckbox = document.createElement("input");
    inStockCheckbox.type = "checkbox";
    inStockCheckbox.addEventListener("change", () => {
      state.filters.in_stock_only = inStockCheckbox.checked;
      void loadResults(true);
    });
    inStockLabel.appendChild(inStockCheckbox);
    inStockLabel.appendChild(document.createTextNode("Mavjud"));
    filterBar.appendChild(inStockLabel);
  }

  async function loadResults(reset: boolean): Promise<void> {
    if (reset) {
      state.filters.cursor = undefined;
      state.nextCursor = null;
      resultsSection.innerHTML = "";
      resultsSection.appendChild(skeletonList(4, 100));
    }
    try {
      const response = await listProducts(state.filters);
      if (reset) resultsSection.innerHTML = "";
      else {
        const loadMoreButton = resultsSection.querySelector("[data-load-more]");
        loadMoreButton?.remove();
      }

      if (reset && response.items.length === 0) {
        resultsSection.appendChild(emptyState(uz.emptyCatalog));
        return;
      }

      for (const product of response.items) {
        resultsSection.appendChild(productCard(product));
      }

      state.nextCursor = response.next_cursor;
      if (state.nextCursor) {
        const loadMoreButton = document.createElement("button");
        loadMoreButton.setAttribute("data-load-more", "true");
        loadMoreButton.className = "button-primary";
        loadMoreButton.textContent = "Ko'proq ko'rsatish";
        loadMoreButton.addEventListener("click", () => {
          state.filters.cursor = state.nextCursor ?? undefined;
          void loadResults(false);
        });
        resultsSection.appendChild(loadMoreButton);
      }
    } catch (error) {
      if (reset) resultsSection.innerHTML = "";
      resultsSection.appendChild(errorState(error, () => void loadResults(reset)));
    }
  }

  try {
    const filtersData = await getFilters();
    renderFilterControls(filtersData);
  } catch {
    // Filters are a UX enhancement — the product list below still loads
    // and works without them if this call fails.
  }

  await loadResults(true);
}
