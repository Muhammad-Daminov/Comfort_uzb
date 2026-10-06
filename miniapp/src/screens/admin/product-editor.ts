import { getProduct } from "../../api/catalog";
import { getFilters } from "../../api/catalog";
import * as vehiclesApi from "../../api/vehicles";
import * as adminApi from "../../api/admin";
import { formatSom } from "../../components/price";
import { skeletonList } from "../../components/loading";
import { errorState } from "../../components/error-state";
import { productMedia } from "../../components/product-media";
import { icon } from "../../components/icons";
import { setBackButton } from "../../telegram";
import { navigate } from "../../router";
import { isOwnerRole } from "../../state/session";

export async function render(container: HTMLElement, params: Record<string, string>): Promise<void> {
  setBackButton(() => navigate("/admin/products"));

  const isNew = params.id === "new";
  const productId = isNew ? null : Number(params.id);

  if (isNew) {
    await renderCreateForm(container);
    return;
  }

  container.appendChild(skeletonList(1, 200));
  try {
    const detail = await getProduct(productId!);
    container.innerHTML = "";
    renderEditor(container, detail, productId!, () => void render(container, params));
  } catch (error) {
    container.innerHTML = "";
    container.appendChild(errorState(error, () => void render(container, params)));
  }
}

// --- small builders ---------------------------------------------------------

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

function hint(text: string): HTMLElement {
  const node = document.createElement("p");
  node.className = "hint";
  node.textContent = text;
  return node;
}

// --- create -----------------------------------------------------------------

async function renderCreateForm(container: HTMLElement): Promise<void> {
  const header = document.createElement("h2");
  header.className = "screen-title";
  header.textContent = "Yangi mahsulot";
  container.appendChild(header);

  // The single most confusing thing about this screen before: it only asks
  // for a name and a brand, so it reads as "this app cannot do images".
  // Images/variants/compatibility all hang off a product id, which does not
  // exist until the product is saved — say so instead of leaving the admin
  // to guess.
  container.appendChild(
    hint("Avval nomi va brendini saqlang. Saqlangandan keyin rasm, variant va mos avtomobillar qo'shiladi."),
  );

  let filters;
  try {
    filters = await getFilters();
  } catch (error) {
    // Used to be an unhandled rejection: the form rendered header + hint
    // and no inputs, with no way to retry.
    container.appendChild(errorState(error, () => void renderCreateForm(container)));
    return;
  }

  const nameInput = document.createElement("input");
  nameInput.placeholder = "Masalan: Salon qoplamasi";
  container.appendChild(field("Nomi", nameInput));

  const brandSelect = document.createElement("select");
  for (const brand of filters.brands) {
    const option = document.createElement("option");
    option.value = String(brand.id);
    option.textContent = brand.name;
    brandSelect.appendChild(option);
  }
  container.appendChild(field("Brend", brandSelect));

  // §P1-3: business scope is exactly these two — no "boshqa" option, so a
  // mistyped/invented type can never reach the backend's CHECK constraint.
  const typeSelect = document.createElement("select");
  for (const [value, label] of [
    ["SIDENA", "Sidena"],
    ["SIDENA_COVER", "Sidena chexoli"],
  ] as const) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    typeSelect.appendChild(option);
  }
  container.appendChild(field("Turi", typeSelect));

  const messageSection = document.createElement("div");
  container.appendChild(messageSection);

  const createButton = document.createElement("button");
  createButton.type = "button";
  createButton.className = "btn btn-pri btn-block";
  createButton.textContent = "Yaratish";
  createButton.addEventListener("click", async () => {
    messageSection.innerHTML = "";
    if (!nameInput.value.trim() || !brandSelect.value) {
      messageSection.appendChild(errorState(new Error("name and brand required")));
      return;
    }
    createButton.disabled = true;
    try {
      const product = await adminApi.adminCreateProduct(
        nameInput.value.trim(), Number(brandSelect.value), undefined,
        typeSelect.value as adminApi.ProductType,
      );
      navigate(`/admin/product/${product.id}`);
    } catch (error) {
      createButton.disabled = false;
      messageSection.appendChild(errorState(error));
    }
  });
  container.appendChild(createButton);
}

// --- edit -------------------------------------------------------------------

const STATUS_BADGE: Record<string, string> = {
  ACTIVE: "badge badge-ok",
  DRAFT: "badge badge-warn",
  ARCHIVED: "badge",
};

function renderEditor(
  container: HTMLElement,
  detail: Awaited<ReturnType<typeof getProduct>>,
  productId: number,
  reload: () => void,
): void {
  const header = document.createElement("h2");
  header.className = "screen-title";
  header.textContent = detail.product.name;
  container.appendChild(header);

  const statusRow = document.createElement("div");
  statusRow.className = "row";
  statusRow.classList.add("mb-12");

  const current = document.createElement("span");
  current.className = STATUS_BADGE[detail.product.status] ?? "badge";
  current.textContent = detail.product.status;
  statusRow.appendChild(current);

  for (const status of ["DRAFT", "ACTIVE", "ARCHIVED"]) {
    if (status === detail.product.status) continue;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "chip";
    button.textContent = `→ ${status}`;
    button.addEventListener("click", () => {
      void adminApi.adminSetProductStatus(productId, status).then(reload);
    });
    statusRow.appendChild(button);
  }
  container.appendChild(statusRow);

  const typeRow = document.createElement("div");
  typeRow.className = "row mb-12";
  const typeLabel = document.createElement("span");
  typeLabel.className = "hint";
  typeLabel.textContent = "Turi:";
  typeRow.appendChild(typeLabel);
  for (const [value, label] of [
    ["SIDENA", "Sidena"],
    ["SIDENA_COVER", "Sidena chexoli"],
  ] as const) {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "chip";
    chip.textContent = label;
    chip.setAttribute("aria-pressed", String(detail.product.product_type === value));
    chip.addEventListener("click", () => {
      void adminApi.adminUpdateProduct(productId, { product_type: value }).then(reload);
    });
    typeRow.appendChild(chip);
  }
  container.appendChild(typeRow);

  renderVariantsSection(container, detail.variants, productId, reload);
  renderImagesSection(container, detail.images, productId, reload);
  renderCompatibilitySection(container, productId);
}

function renderVariantsSection(
  container: HTMLElement,
  variants: unknown[],
  productId: number,
  reload: () => void,
): void {
  container.appendChild(sectionHeading("Variantlar"));

  const typed = variants as Array<{
    id: number;
    sku: string;
    material: string | null;
    price: number;
    stock_on_hand: number;
    stock_reserved: number;
    status: string;
  }>;

  if (typed.length === 0) {
    container.appendChild(hint("Hali variant yo'q. Sotuv uchun kamida bitta variant kerak."));
  } else {
    const list = document.createElement("div");
    list.className = "list";
    for (const variant of typed) {
      const row = document.createElement("div");
      row.className = "list-item";

      const text = document.createElement("div");
      text.className = "grow";
      const sku = document.createElement("div");
      sku.className = "list-title num";
      sku.textContent = variant.sku;
      text.appendChild(sku);
      const price = document.createElement("div");
      price.className = "list-sub";
      price.textContent = variant.material ? `${formatSom(variant.price)} · ${variant.material}` : formatSom(variant.price);
      text.appendChild(price);
      row.appendChild(text);

      const available = variant.stock_on_hand - variant.stock_reserved;
      const stock = document.createElement("span");
      stock.className = available > 0 ? "badge badge-ok" : "badge badge-dang";
      stock.textContent = `Stok: ${available}`;
      row.appendChild(stock);

      list.appendChild(row);

      // §12/§13 of the v2 brief: cost price is financial data — ADMIN must
      // never see or edit it, only OWNER. This is a UX-only gate (matches
      // the existing isOwnerRole() convention elsewhere in the Mini App);
      // the server enforces finance.view on both the GET and PATCH
      // cost-price endpoints regardless of what this renders.
      if (isOwnerRole()) {
        list.appendChild(renderCostPriceRow(variant.id));
      }
    }
    container.appendChild(list);
  }

  const form = document.createElement("div");
  form.className = "card";
  form.classList.add("mt-12");

  const skuInput = document.createElement("input");
  skuInput.placeholder = "SKU";
  form.appendChild(field("SKU", skuInput));

  const priceInput = document.createElement("input");
  priceInput.placeholder = "Narx";
  priceInput.type = "number";
  priceInput.inputMode = "numeric";
  form.appendChild(field("Narx (so'm)", priceInput));

  // §P1-3: free text, not a fixed list — "Koja"/"Eco-koja" are examples,
  // not the only allowed values (unlike product_type, which is a real
  // business-defined enum).
  const materialInput = document.createElement("input");
  materialInput.placeholder = "Masalan: Koja, Eco-koja";
  form.appendChild(field("Material (ixtiyoriy)", materialInput));

  const variantMessage = document.createElement("div");
  const addVariantButton = document.createElement("button");
  addVariantButton.type = "button";
  addVariantButton.className = "btn btn-pri btn-block";
  addVariantButton.textContent = "+ Variant qo'shish";
  addVariantButton.addEventListener("click", () => {
    variantMessage.innerHTML = "";
    const price = Number(priceInput.value);
    if (!skuInput.value.trim() || !price) {
      variantMessage.appendChild(errorState(new Error("sku and price required")));
      return;
    }
    void adminApi
      .adminCreateVariant(productId, skuInput.value.trim(), price, undefined, 0, materialInput.value.trim() || undefined)
      .then(reload)
      .catch((error: unknown) => variantMessage.appendChild(errorState(error)));
  });
  form.appendChild(addVariantButton);
  form.appendChild(variantMessage);
  container.appendChild(form);
}

function renderCostPriceRow(variantId: number): HTMLElement {
  const row = document.createElement("div");
  row.className = "list-item";
  const text = document.createElement("div");
  text.className = "grow hint";
  text.textContent = "Tannarx: ...";
  row.appendChild(text);

  const editButton = document.createElement("button");
  editButton.type = "button";
  editButton.className = "btn";
  editButton.textContent = "Tahrirlash";
  row.appendChild(editButton);

  void adminApi
    .adminGetVariantCostPrice(variantId)
    .then((result) => {
      text.textContent = result.cost_price === null ? "Tannarx: kiritilmagan" : `Tannarx: ${formatSom(result.cost_price)}`;
    })
    .catch((error: unknown) => {
      text.textContent = "Tannarx: xatolik";
      row.appendChild(errorState(error));
    });

  editButton.addEventListener("click", () => {
    const input = window.prompt("Yangi tannarx (so'mda):");
    if (!input) return;
    const value = Number(input.replace(/\D/g, ""));
    if (!Number.isFinite(value) || value < 0) return;
    void adminApi
      .adminSetVariantCostPrice(variantId, value)
      .then((result) => {
        text.textContent = `Tannarx: ${formatSom(result.cost_price)}`;
      })
      .catch((error: unknown) => row.appendChild(errorState(error)));
  });

  return row;
}

function renderImagesSection(
  container: HTMLElement,
  images: unknown[],
  productId: number,
  reload: () => void,
): void {
  container.appendChild(sectionHeading("Rasmlar"));

  const typed = images as Array<{ id: number; is_primary: boolean; signed_url: string | null }>;

  if (typed.length === 0) {
    container.appendChild(hint("Rasm yo'q. Birinchi yuklangan rasm avtomatik asosiy bo'ladi."));
  } else {
    if (typed.length > 1) {
      container.appendChild(hint("Tartibni o'zgartirish uchun strelkalardan foydalaning."));
    }

    const grid = document.createElement("div");
    grid.className = "image-grid";

    // §P2-3: no drag-and-drop dependency — up/down swap against the
    // product's current image order (`typed` is already sorted by
    // sort_order, ADR-13/repository.get_images_for_product).
    function moveImage(index: number, direction: -1 | 1): void {
      const target = index + direction;
      if (target < 0 || target >= typed.length) return;
      const reordered = typed.map((i) => i.id);
      [reordered[index], reordered[target]] = [reordered[target], reordered[index]];
      void adminApi.adminReorderImages(productId, reordered).then(reload);
    }

    typed.forEach((image, index) => {
      const cell = document.createElement("div");
      cell.className = "image-cell";

      // Detal endpointi ADR-13 bo'yicha har rasmga imzolangan havola
      // qaytaradi. `productMedia` yuklanmagan holatni ham qoplaydi —
      // muddati o'tgan imzo buzilgan rasm belgisi bo'lib ko'rinmaydi.
      cell.appendChild(productMedia(image.signed_url, "", { size: "full" }));

      if (image.is_primary) {
        const mark = document.createElement("span");
        mark.className = "badge badge-acc image-cell-flag";
        mark.textContent = "Asosiy";
        cell.appendChild(mark);
      }

      const actions = document.createElement("div");
      actions.className = "image-cell-actions";

      if (typed.length > 1) {
        const upButton = document.createElement("button");
        upButton.type = "button";
        upButton.className = "btn btn-out btn-sm";
        upButton.disabled = index === 0;
        upButton.appendChild(icon("arrow-up", 16));
        upButton.addEventListener("click", () => {
          upButton.disabled = true;
          moveImage(index, -1);
        });
        actions.appendChild(upButton);

        const downButton = document.createElement("button");
        downButton.type = "button";
        downButton.className = "btn btn-out btn-sm";
        downButton.disabled = index === typed.length - 1;
        downButton.appendChild(icon("arrow-down", 16));
        downButton.addEventListener("click", () => {
          downButton.disabled = true;
          moveImage(index, 1);
        });
        actions.appendChild(downButton);
      }

      if (!image.is_primary) {
        const primaryButton = document.createElement("button");
        primaryButton.type = "button";
        primaryButton.className = "btn btn-sec btn-sm grow";
        primaryButton.textContent = "Asosiy";
        primaryButton.addEventListener("click", () => {
          primaryButton.disabled = true;
          void adminApi.adminSetPrimaryImage(productId, image.id).then(reload);
        });
        actions.appendChild(primaryButton);
      }

      const replaceButton = document.createElement("button");
      replaceButton.type = "button";
      replaceButton.className = "btn btn-sec btn-sm";
      replaceButton.textContent = "Almashtirish";
      actions.appendChild(replaceButton);

      const removeButton = document.createElement("button");
      removeButton.type = "button";
      removeButton.className = "btn btn-dang btn-sm";
      removeButton.textContent = "O'chirish";
      removeButton.addEventListener("click", () => {
        removeButton.disabled = true;
        void adminApi.adminRemoveImage(productId, image.id).then(reload);
      });
      actions.appendChild(removeButton);

      cell.appendChild(actions);

      // §P1-4: "Replace image" — select -> preview -> confirm -> old
      // image replaced. Composed from the three existing endpoints
      // (upload/set-primary/delete) in sequence; no new backend endpoint,
      // no new authorization rule — the same products.update permission
      // every action in this section already requires enforces this too.
      const replacePicker = document.createElement("input");
      replacePicker.type = "file";
      replacePicker.accept = "image/*";
      replacePicker.style.display = "none";
      cell.appendChild(replacePicker);

      replaceButton.addEventListener("click", () => replacePicker.click());

      replacePicker.addEventListener("change", () => {
        const file = replacePicker.files?.[0];
        if (!file) return;

        const objectUrl = URL.createObjectURL(file);
        cell.innerHTML = "";
        cell.appendChild(replacePicker); // keep the input alive in the DOM, just hidden

        const preview = document.createElement("img");
        preview.className = "pm-img pm-full";
        preview.src = objectUrl;
        cell.appendChild(preview);

        const confirmBar = document.createElement("div");
        confirmBar.className = "image-cell-actions";

        const confirmMessage = document.createElement("div");

        const confirmButton = document.createElement("button");
        confirmButton.type = "button";
        confirmButton.className = "btn btn-pri btn-sm grow";
        confirmButton.textContent = "Tasdiqlash";
        confirmButton.addEventListener("click", () => {
          confirmButton.disabled = true;
          cancelButton.disabled = true;
          void adminApi
            .adminAddImage(productId, file)
            .then((newImage) =>
              image.is_primary
                ? adminApi.adminSetPrimaryImage(productId, newImage.id).then(() => newImage)
                : newImage,
            )
            .then(() => adminApi.adminRemoveImage(productId, image.id))
            .then(() => {
              URL.revokeObjectURL(objectUrl);
              reload();
            })
            .catch((error: unknown) => {
              confirmMessage.appendChild(errorState(error));
              confirmButton.disabled = false;
              cancelButton.disabled = false;
            });
        });
        confirmBar.appendChild(confirmButton);

        const cancelButton = document.createElement("button");
        cancelButton.type = "button";
        cancelButton.className = "btn btn-out btn-sm";
        cancelButton.textContent = "Bekor qilish";
        cancelButton.addEventListener("click", () => {
          URL.revokeObjectURL(objectUrl);
          reload();
        });
        confirmBar.appendChild(cancelButton);

        cell.appendChild(confirmBar);
        cell.appendChild(confirmMessage);
      });

      grid.appendChild(cell);
    });
    container.appendChild(grid);
  }

  const uploadCard = document.createElement("div");
  uploadCard.className = "card mt-12";

  const fileInput = document.createElement("input");
  fileInput.type = "file";
  fileInput.accept = "image/*";
  uploadCard.appendChild(field("Rasm yuklash", fileInput));

  const uploadMessage = document.createElement("div");
  fileInput.addEventListener("change", () => {
    const file = fileInput.files?.[0];
    if (!file) return;
    uploadMessage.innerHTML = "";
    fileInput.disabled = true;
    const progress = document.createElement("p");
    progress.className = "hint";
    progress.textContent = "Yuklanmoqda…";
    uploadMessage.appendChild(progress);
    void adminApi
      .adminAddImage(productId, file)
      .then(reload)
      .catch((error: unknown) => {
        fileInput.disabled = false;
        uploadMessage.innerHTML = "";
        uploadMessage.appendChild(errorState(error));
      });
  });
  uploadCard.appendChild(uploadMessage);
  container.appendChild(uploadCard);
}

function renderCompatibilitySection(container: HTMLElement, productId: number): void {
  container.appendChild(sectionHeading("Mos avtomobillar"));

  const listSection = document.createElement("div");
  container.appendChild(listSection);

  async function loadList(): Promise<void> {
    listSection.innerHTML = "";
    const { items } = await adminApi.adminListCompatibilities(productId);
    if (items.length === 0) {
      listSection.appendChild(hint("Hali mos avtomobil belgilanmagan."));
      return;
    }
    const list = document.createElement("div");
    list.className = "list";
    for (const item of items) {
      const row = document.createElement("div");
      row.className = "list-item";

      const text = document.createElement("div");
      text.className = "grow";
      text.textContent = `Generatsiya #${item.generation_id}${
        item.year_from ? ` (${item.year_from}-${item.year_to ?? ""})` : ""
      }`;
      row.appendChild(text);

      const removeButton = document.createElement("button");
      removeButton.type = "button";
      removeButton.className = "btn btn-dang btn-sm";
      removeButton.textContent = "O'chirish";
      removeButton.addEventListener("click", () => {
        void adminApi.adminRemoveCompatibility(productId, item.id).then(loadList);
      });
      row.appendChild(removeButton);

      list.appendChild(row);
    }
    listSection.appendChild(list);
  }
  void loadList();

  const form = document.createElement("div");
  form.className = "card";
  form.classList.add("mt-12");

  const brandSelect = document.createElement("select");
  const modelSelect = document.createElement("select");
  const generationSelect = document.createElement("select");
  form.appendChild(field("Avto brend", brandSelect));
  form.appendChild(field("Model", modelSelect));
  form.appendChild(field("Generatsiya", generationSelect));

  const compatMessage = document.createElement("div");
  const addButton = document.createElement("button");
  addButton.type = "button";
  addButton.className = "btn btn-pri btn-block";
  addButton.textContent = "+ Qo'shish";

  void vehiclesApi.listCarBrands().then((res) => {
    for (const brand of res.items) {
      const option = document.createElement("option");
      option.value = String(brand.id);
      option.textContent = brand.name;
      brandSelect.appendChild(option);
    }
    if (res.items.length) void loadModels(res.items[0].id);
  });

  async function loadModels(carBrandId: number): Promise<void> {
    modelSelect.innerHTML = "";
    const res = await vehiclesApi.listCarModels(carBrandId);
    for (const model of res.items) {
      const option = document.createElement("option");
      option.value = String(model.id);
      option.textContent = model.name;
      modelSelect.appendChild(option);
    }
    if (res.items.length) await loadGenerations(res.items[0].id);
  }

  async function loadGenerations(carModelId: number): Promise<void> {
    generationSelect.innerHTML = "";
    const res = await vehiclesApi.listCarGenerations(carModelId);
    for (const generation of res.items) {
      const option = document.createElement("option");
      option.value = String(generation.id);
      option.textContent = generation.name;
      generationSelect.appendChild(option);
    }
  }

  brandSelect.addEventListener("change", () => void loadModels(Number(brandSelect.value)));
  modelSelect.addEventListener("change", () => void loadGenerations(Number(modelSelect.value)));

  addButton.addEventListener("click", () => {
    compatMessage.innerHTML = "";
    if (!generationSelect.value) return;
    void adminApi
      .adminAddCompatibility(productId, Number(generationSelect.value))
      .then(loadList)
      .catch((error: unknown) => compatMessage.appendChild(errorState(error)));
  });

  form.appendChild(addButton);
  form.appendChild(compatMessage);
  container.appendChild(form);
}
