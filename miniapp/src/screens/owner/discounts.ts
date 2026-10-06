import * as discountsApi from "../../api/discounts";
import type { Discount, DiscountKind, DiscountTargetType } from "../../api/discounts";
import { formatSom } from "../../components/price";
import { skeletonList } from "../../components/loading";
import { emptyState } from "../../components/empty-state";
import { errorState } from "../../components/error-state";
import { setBackButton } from "../../telegram";
import { navigate } from "../../router";

// §P2-4: owner-only discount management screen. CRUD over the existing
// discounts/discount_targets model (migration 0005_pricing) via the new
// /owner/discounts endpoints (migration 0020/0021) — no new pricing
// semantics invented here, only list/create/edit/activate-deactivate.

const TARGET_LABELS: Record<DiscountTargetType, string> = {
  ALL: "Barcha mahsulotlar",
  PRODUCT: "Mahsulot",
  VARIANT: "Variant",
  BRAND: "Brend",
  CAR_MODEL: "Avtomobil modeli",
};

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

function formatDiscountValue(discount: Discount): string {
  return discount.kind === "PERCENT" ? `${discount.value}%` : formatSom(discount.value);
}

export async function render(container: HTMLElement): Promise<void> {
  container.replaceChildren();
  setBackButton(() => navigate("/owner"));

  const header = document.createElement("h1");
  header.className = "screen-title";
  header.textContent = "Chegirmalar";
  container.appendChild(header);

  const listSection = document.createElement("div");
  const createSection = document.createElement("div");
  container.appendChild(listSection);
  container.appendChild(createSection);

  async function reload(): Promise<void> {
    listSection.replaceChildren();
    listSection.appendChild(skeletonList(3, 90));
    try {
      const { items } = await discountsApi.listDiscounts();
      renderList(listSection, items, reload);
    } catch (error) {
      listSection.replaceChildren();
      listSection.appendChild(errorState(error, () => void reload()));
    }
  }

  renderCreateForm(createSection, reload);
  await reload();
}

function renderList(container: HTMLElement, discounts: Discount[], reload: () => void): void {
  container.replaceChildren();
  container.appendChild(sectionHeading("Mavjud chegirmalar"));

  if (discounts.length === 0) {
    container.appendChild(emptyState("Hali chegirma yo'q. Pastdan birinchi chegirmani qo'shing.", undefined, "percent"));
    return;
  }

  for (const discount of discounts) {
    container.appendChild(renderDiscountCard(discount, reload));
  }
}

function renderDiscountCard(discount: Discount, reload: () => void): HTMLElement {
  const card = document.createElement("div");
  card.className = "card mb-12";

  const top = document.createElement("div");
  top.className = "row-between";

  const titleWrap = document.createElement("div");
  const title = document.createElement("div");
  title.className = "list-title";
  title.textContent = discount.name;
  titleWrap.appendChild(title);

  const sub = document.createElement("div");
  sub.className = "list-sub";
  sub.textContent = formatDiscountValue(discount);
  titleWrap.appendChild(sub);
  top.appendChild(titleWrap);

  const statusBadge = document.createElement("span");
  statusBadge.className = discount.is_active ? "badge badge-ok" : "badge";
  statusBadge.textContent = discount.is_active ? "Faol" : "Nofaol";
  top.appendChild(statusBadge);

  card.appendChild(top);

  const targetsWrap = document.createElement("div");
  targetsWrap.className = "chip-row mt-12";
  if (discount.targets.length === 0) {
    const chip = document.createElement("span");
    chip.className = "hint";
    chip.textContent = "Nishon belgilanmagan";
    targetsWrap.appendChild(chip);
  } else {
    for (const target of discount.targets) {
      const chip = document.createElement("span");
      chip.className = "chip";
      chip.textContent =
        target.target_type === "ALL"
          ? TARGET_LABELS.ALL
          : `${TARGET_LABELS[target.target_type]} #${target.target_id}`;
      targetsWrap.appendChild(chip);
    }
  }
  card.appendChild(targetsWrap);

  const actions = document.createElement("div");
  actions.className = "row-between mt-12";

  const editButton = document.createElement("button");
  editButton.type = "button";
  editButton.className = "btn btn-out btn-sm";
  editButton.textContent = "Tahrirlash";
  actions.appendChild(editButton);

  const toggleButton = document.createElement("button");
  toggleButton.type = "button";
  toggleButton.className = discount.is_active ? "btn btn-dang btn-sm" : "btn btn-pri btn-sm";
  toggleButton.textContent = discount.is_active ? "Faolsizlantirish" : "Faollashtirish";
  toggleButton.addEventListener("click", () => {
    toggleButton.disabled = true;
    void discountsApi
      .setDiscountActive(discount.id, !discount.is_active)
      .then(reload)
      .catch((error: unknown) => {
        toggleButton.disabled = false;
        card.appendChild(errorState(error));
      });
  });
  actions.appendChild(toggleButton);

  card.appendChild(actions);

  const editForm = document.createElement("div");
  editForm.className = "mt-12";
  editForm.style.display = "none";
  card.appendChild(editForm);

  editButton.addEventListener("click", () => {
    const isOpen = editForm.style.display !== "none";
    editForm.style.display = isOpen ? "none" : "block";
    if (!isOpen) {
      editForm.replaceChildren();
      editForm.appendChild(buildEditForm(discount, reload));
    }
  });

  return card;
}

function buildEditForm(discount: Discount, reload: () => void): HTMLElement {
  const wrap = document.createElement("div");

  const nameInput = document.createElement("input");
  nameInput.value = discount.name;
  wrap.appendChild(field("Nomi", nameInput));

  const kindSelect = document.createElement("select");
  for (const kind of ["PERCENT", "FIXED"] as DiscountKind[]) {
    const option = document.createElement("option");
    option.value = kind;
    option.textContent = kind === "PERCENT" ? "Foiz (%)" : "Aniq summa (so'm)";
    option.selected = kind === discount.kind;
    kindSelect.appendChild(option);
  }
  wrap.appendChild(field("Turi", kindSelect));

  const valueInput = document.createElement("input");
  valueInput.type = "number";
  valueInput.value = String(discount.value);
  wrap.appendChild(field("Qiymati", valueInput));

  const priorityInput = document.createElement("input");
  priorityInput.type = "number";
  priorityInput.value = String(discount.priority);
  wrap.appendChild(field("Ustuvorlik", priorityInput));

  const saveMessage = document.createElement("div");

  const saveButton = document.createElement("button");
  saveButton.type = "button";
  saveButton.className = "btn btn-pri btn-sm btn-block";
  saveButton.textContent = "Saqlash";
  saveButton.addEventListener("click", () => {
    const value = Number(valueInput.value);
    const priority = Number(priorityInput.value);
    if (!nameInput.value.trim() || !Number.isFinite(value) || value < 0 || !Number.isFinite(priority)) {
      saveMessage.replaceChildren();
      saveMessage.appendChild(errorState(new Error("Ma'lumotlar to'g'ri emas")));
      return;
    }
    saveButton.disabled = true;
    void discountsApi
      .updateDiscount(discount.id, {
        name: nameInput.value.trim(),
        kind: kindSelect.value as DiscountKind,
        value,
        priority,
      })
      .then(reload)
      .catch((error: unknown) => {
        saveButton.disabled = false;
        saveMessage.replaceChildren();
        saveMessage.appendChild(errorState(error));
      });
  });
  wrap.appendChild(saveButton);
  wrap.appendChild(saveMessage);

  return wrap;
}

function renderCreateForm(container: HTMLElement, reload: () => void): void {
  container.appendChild(sectionHeading("Yangi chegirma"));

  const nameInput = document.createElement("input");
  nameInput.placeholder = "Masalan: Yozgi chegirma";
  container.appendChild(field("Nomi", nameInput));

  const kindSelect = document.createElement("select");
  const percentOption = document.createElement("option");
  percentOption.value = "PERCENT";
  percentOption.textContent = "Foiz (%)";
  const fixedOption = document.createElement("option");
  fixedOption.value = "FIXED";
  fixedOption.textContent = "Aniq summa (so'm)";
  kindSelect.appendChild(percentOption);
  kindSelect.appendChild(fixedOption);
  container.appendChild(field("Turi", kindSelect));

  const valueInput = document.createElement("input");
  valueInput.type = "number";
  valueInput.placeholder = "10";
  container.appendChild(field("Qiymati", valueInput));

  const targetSelect = document.createElement("select");
  for (const [value, label] of Object.entries(TARGET_LABELS) as Array<[DiscountTargetType, string]>) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    targetSelect.appendChild(option);
  }
  container.appendChild(field("Nishon turi", targetSelect));

  const targetIdInput = document.createElement("input");
  targetIdInput.type = "number";
  targetIdInput.placeholder = "ID (masalan mahsulot yoki brend ID'si)";
  const targetIdField = field("Nishon ID", targetIdInput);
  container.appendChild(targetIdField);

  function syncTargetIdVisibility(): void {
    targetIdField.style.display = targetSelect.value === "ALL" ? "none" : "flex";
  }
  targetSelect.addEventListener("change", syncTargetIdVisibility);
  syncTargetIdVisibility();

  container.appendChild(hint("\"Barcha mahsulotlar\" tanlansa, ID kiritish shart emas."));

  const createMessage = document.createElement("div");

  const createButton = document.createElement("button");
  createButton.type = "button";
  createButton.className = "btn btn-pri btn-block";
  createButton.textContent = "Chegirma qo'shish";
  createButton.addEventListener("click", () => {
    createMessage.replaceChildren();
    const name = nameInput.value.trim();
    const value = Number(valueInput.value);
    const targetType = targetSelect.value as DiscountTargetType;
    const targetId = targetType === "ALL" ? null : Number(targetIdInput.value);

    if (!name || !Number.isFinite(value) || value < 0) {
      createMessage.appendChild(errorState(new Error("Ma'lumotlar to'g'ri emas")));
      return;
    }
    if (targetType !== "ALL" && (!targetId || !Number.isFinite(targetId))) {
      createMessage.appendChild(errorState(new Error("Nishon ID kiritilishi kerak")));
      return;
    }

    createButton.disabled = true;
    void discountsApi
      .createDiscount({
        name,
        kind: kindSelect.value as DiscountKind,
        value,
        targets: [{ target_type: targetType, target_id: targetId }],
      })
      .then(() => {
        nameInput.value = "";
        valueInput.value = "";
        targetIdInput.value = "";
        return reload();
      })
      .catch((error: unknown) => {
        createMessage.replaceChildren();
        createMessage.appendChild(errorState(error));
      })
      .finally(() => {
        createButton.disabled = false;
      });
  });
  container.appendChild(createButton);
  container.appendChild(createMessage);
}
