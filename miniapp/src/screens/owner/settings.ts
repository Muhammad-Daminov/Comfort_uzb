import { getSettings, putSettings } from "../../api/owner";
import { skeletonList } from "../../components/loading";
import { emptyState } from "../../components/empty-state";
import { errorState } from "../../components/error-state";
import { setBackButton } from "../../telegram";
import { navigate } from "../../router";

// Visual-only migration to the premium design system (§P3B-1) — same
// generic key/value getSettings/putSettings calls as before (Phase 07's
// own explicit decision, see docs/tasks/Phase-07-Owner.md: the TZ never
// specifies what a "setting" is, so this stays a generic editor rather
// than a form for invented fields).

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

export async function render(container: HTMLElement): Promise<void> {
  container.replaceChildren();
  setBackButton(() => navigate("/owner"));

  const header = document.createElement("h1");
  header.className = "screen-title";
  header.textContent = "Sozlamalar";
  container.appendChild(header);

  const hint = document.createElement("p");
  hint.className = "hint mb-16";
  hint.textContent = "Umumiy kalit-qiymat saqlash — hozircha oldindan belgilangan sozlama yo'q.";
  container.appendChild(hint);

  const listSection = document.createElement("div");
  listSection.className = "mb-16";
  container.appendChild(listSection);
  listSection.appendChild(skeletonList(2, 50));

  const keyInput = document.createElement("input");
  keyInput.placeholder = "Kalit (masalan: store_name)";
  const valueInput = document.createElement("input");
  valueInput.placeholder = "Qiymat";
  const saveButton = document.createElement("button");
  saveButton.type = "button";
  saveButton.className = "btn btn-pri btn-block";
  saveButton.textContent = "Saqlash";
  const saveMessage = document.createElement("div");

  container.appendChild(field("Kalit", keyInput));
  container.appendChild(field("Qiymat", valueInput));
  container.appendChild(saveButton);
  container.appendChild(saveMessage);

  async function load(): Promise<void> {
    listSection.replaceChildren();
    try {
      const settings = await getSettings();
      const keys = Object.keys(settings);
      if (keys.length === 0) {
        listSection.appendChild(emptyState("Sozlamalar hali kiritilmagan.", undefined, "grid"));
        return;
      }
      for (const key of keys) {
        const row = document.createElement("div");
        row.className = "card mb-8 row-between";
        const keyLabel = document.createElement("span");
        keyLabel.className = "t-body num";
        keyLabel.textContent = key;
        row.appendChild(keyLabel);
        const valueLabel = document.createElement("span");
        valueLabel.className = "hint num";
        valueLabel.textContent = JSON.stringify(settings[key]);
        row.appendChild(valueLabel);
        listSection.appendChild(row);
      }
    } catch (error) {
      listSection.replaceChildren();
      listSection.appendChild(errorState(error, () => void load()));
    }
  }

  saveButton.addEventListener("click", () => {
    saveMessage.replaceChildren();
    if (!keyInput.value.trim()) {
      saveMessage.appendChild(errorState(new Error("key required")));
      return;
    }
    saveButton.disabled = true;
    void putSettings({ [keyInput.value.trim()]: valueInput.value })
      .then(() => {
        keyInput.value = "";
        valueInput.value = "";
        return load();
      })
      .catch((error: unknown) => saveMessage.appendChild(errorState(error)))
      .finally(() => {
        saveButton.disabled = false;
      });
  });

  await load();
}
