import { listProducts, type ProductListItem } from "../../api/catalog";
import * as adminApi from "../../api/admin";
import { formatSom } from "../../components/price";
import { productMedia } from "../../components/product-media";
import { skeletonList } from "../../components/loading";
import { emptyState } from "../../components/empty-state";
import { errorState } from "../../components/error-state";
import { setBackButton } from "../../telegram";
import { navigate } from "../../router";
import { icon } from "../../components/icons";

export async function render(container: HTMLElement): Promise<void> {
  container.replaceChildren(); // retry re-renders into the same container — never stack a second copy
  setBackButton(() => navigate("/admin"));

  const header = document.createElement("h2");
  header.textContent = "Mahsulotlar";
  container.appendChild(header);

  const createButton = document.createElement("button");
  createButton.type = "button";
  createButton.className = "btn btn-pri btn-block mb-12";
  createButton.textContent = "+ Yangi mahsulot";
  createButton.addEventListener("click", () => navigate("/admin/product/new"));
  container.appendChild(createButton);

  const listSection = document.createElement("div");
  container.appendChild(listSection);
  listSection.appendChild(skeletonList(4, 76));

  try {
    // Admin needs to see DRAFT/ARCHIVED products too, not just ACTIVE —
    // GET /catalog/products only ever returns ACTIVE (it's the public
    // listing endpoint); reusing it here is a deliberate simplification
    // (see Phase-06 report "Known limitations") rather than adding a
    // separate admin listing endpoint for a screen that's still usable
    // without it (products are ACTIVE for most of their lifetime; a newly
    // created DRAFT product is reachable directly by its id right after
    // creation, since admin_create_product returns it).
    const response = await listProducts({ limit: 50 });
    listSection.innerHTML = "";
    if (response.items.length === 0) {
      listSection.appendChild(emptyState("Mahsulotlar yo'q."));
      return;
    }
    const list = document.createElement("div");
    list.className = "list";
    for (const product of response.items) {
      list.appendChild(productRow(product, () => void render(container)));
    }
    listSection.appendChild(list);
  } catch (error) {
    listSection.innerHTML = "";
    listSection.appendChild(errorState(error, () => void render(container)));
  }
}

/** Rasm + nom + narx + stok + amallar. Ilgari bu bitta matn qatori edi
 *  ("Nom — narx"), shuning uchun adminda qaysi mahsulot ekanini rasmdan
 *  ajratib bo'lmasdi. */
function productRow(product: ProductListItem, reload: () => void): HTMLElement {
  const row = document.createElement("div");
  row.className = "media-row";

  row.appendChild(productMedia(product.primary_image_url, product.name, { size: "sm" }));

  const body = document.createElement("div");
  body.className = "media-row-body";

  const name = document.createElement("div");
  name.className = "media-row-title";
  name.textContent = product.name;
  body.appendChild(name);

  const meta = document.createElement("div");
  meta.className = "row";

  const price = document.createElement("span");
  price.className = "media-row-sub num";
  price.textContent = `${formatSom(product.min_price)}dan`;
  meta.appendChild(price);

  const stock = document.createElement("span");
  const available = product.total_available;
  stock.className = available <= 0 ? "badge badge-dang" : available <= 3 ? "badge badge-warn" : "badge";
  stock.textContent = available <= 0 ? "Tugagan" : `Stok: ${available}`;
  meta.appendChild(stock);

  body.appendChild(meta);
  row.appendChild(body);

  const actions = document.createElement("div");
  actions.className = "media-row-actions";

  const edit = document.createElement("button");
  edit.type = "button";
  edit.className = "icon-btn";
  edit.appendChild(icon("edit", 16));
  edit.setAttribute("aria-label", `${product.name} — tahrirlash`);
  edit.addEventListener("click", () => navigate(`/admin/product/${product.id}`));
  actions.appendChild(edit);

  // O'chirish emas, ARXIVLASH: §12.2 bo'yicha `comfort_app` da DELETE
  // huquqi umuman yo'q va buyurtmalar tarixi mahsulotga bog'liq qoladi.
  // Tugma nima qilishini aniq aytadi (DESIGN.md matn qoidalari).
  const archive = document.createElement("button");
  archive.type = "button";
  archive.className = "icon-btn icon-btn-dang";
  archive.appendChild(icon("trash", 16));
  archive.setAttribute("aria-label", `${product.name} — arxivlash`);
  archive.addEventListener("click", () => {
    if (!window.confirm(`"${product.name}" arxivlansinmi? Katalogdan yo'qoladi, buyurtmalar tarixida qoladi.`)) return;
    archive.disabled = true;
    void adminApi
      .adminSetProductStatus(product.id, "ARCHIVED")
      .then(reload)
      .catch((error: unknown) => {
        archive.disabled = false;
        row.appendChild(errorState(error));
      });
  });
  actions.appendChild(archive);

  row.appendChild(actions);
  return row;
}
