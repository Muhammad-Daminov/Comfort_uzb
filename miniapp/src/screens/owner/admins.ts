import { listAdmins, createAdmin, deactivateAdmin, reactivateAdmin } from "../../api/owner";
import { skeletonList } from "../../components/loading";
import { emptyState } from "../../components/empty-state";
import { errorState } from "../../components/error-state";
import { setBackButton } from "../../telegram";
import { navigate } from "../../router";

// Visual-only migration to the premium design system (§P3B-1) — same
// list/create/deactivate/reactivate calls as before.

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

export async function render(container: HTMLElement): Promise<void> {
  container.replaceChildren();
  setBackButton(() => navigate("/owner"));

  const header = document.createElement("h1");
  header.className = "screen-title";
  header.textContent = "Administratorlar";
  container.appendChild(header);

  container.appendChild(sectionHeading("Yangi admin"));
  const telegramIdInput = document.createElement("input");
  telegramIdInput.type = "number";
  telegramIdInput.placeholder = "Telegram ID";
  const nameInput = document.createElement("input");
  nameInput.placeholder = "Ism (ixtiyoriy)";
  const createButton = document.createElement("button");
  createButton.type = "button";
  createButton.className = "btn btn-pri btn-block";
  createButton.textContent = "+ Admin qo'shish";
  const createMessage = document.createElement("div");

  container.appendChild(field("Telegram ID", telegramIdInput));
  container.appendChild(field("Ism", nameInput));
  container.appendChild(createButton);
  container.appendChild(createMessage);

  const listSection = document.createElement("div");
  listSection.className = "mt-16";
  container.appendChild(listSection);

  async function load(): Promise<void> {
    listSection.replaceChildren();
    listSection.appendChild(skeletonList(3, 70));
    try {
      const response = await listAdmins();
      listSection.replaceChildren();
      if (response.items.length === 0) {
        listSection.appendChild(emptyState("Administratorlar yo'q.", undefined, "shield"));
        return;
      }
      listSection.appendChild(sectionHeading("Ro'yxat"));
      for (const admin of response.items) {
        const row = document.createElement("div");
        row.className = "card mb-8";

        const top = document.createElement("div");
        top.className = "row-between";
        const info = document.createElement("span");
        info.className = "list-title";
        info.textContent = admin.first_name ?? `#${admin.telegram_id}`;
        top.appendChild(info);
        const badge = document.createElement("span");
        badge.className = admin.status === "ACTIVE" ? "badge badge-ok" : "badge";
        badge.textContent = admin.status;
        top.appendChild(badge);
        row.appendChild(top);

        const actionButton = document.createElement("button");
        actionButton.type = "button";
        actionButton.className = "btn btn-out btn-sm btn-block mt-12";
        if (admin.status === "ACTIVE") {
          actionButton.textContent = "Faolsizlantirish";
          actionButton.addEventListener("click", () => {
            actionButton.disabled = true;
            void deactivateAdmin(admin.id)
              .then(load)
              .catch((error: unknown) => {
                actionButton.disabled = false;
                row.appendChild(errorState(error));
              });
          });
        } else {
          actionButton.textContent = "Faollashtirish";
          actionButton.addEventListener("click", () => {
            actionButton.disabled = true;
            void reactivateAdmin(admin.id)
              .then(load)
              .catch((error: unknown) => {
                actionButton.disabled = false;
                row.appendChild(errorState(error));
              });
          });
        }
        row.appendChild(actionButton);
        listSection.appendChild(row);
      }
    } catch (error) {
      listSection.replaceChildren();
      listSection.appendChild(errorState(error, () => void load()));
    }
  }

  createButton.addEventListener("click", () => {
    createMessage.replaceChildren();
    const telegramId = Number(telegramIdInput.value);
    if (!telegramId) {
      createMessage.appendChild(errorState(new Error("telegram id required")));
      return;
    }
    createButton.disabled = true;
    void createAdmin(telegramId, nameInput.value.trim() || undefined)
      .then(() => {
        telegramIdInput.value = "";
        nameInput.value = "";
        return load();
      })
      .catch((error: unknown) => createMessage.appendChild(errorState(error)))
      .finally(() => {
        createButton.disabled = false;
      });
  });

  await load();
}
