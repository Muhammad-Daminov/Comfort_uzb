import { listAuditLogs } from "../../api/owner";
import { skeletonList } from "../../components/loading";
import { emptyState } from "../../components/empty-state";
import { errorState } from "../../components/error-state";
import { setBackButton } from "../../telegram";
import { navigate } from "../../router";

// Visual-only migration to the premium design system (§P3B-1) — same
// cursor-paginated listAuditLogs call/behavior as before.

export async function render(container: HTMLElement): Promise<void> {
  container.replaceChildren();
  setBackButton(() => navigate("/owner"));

  const header = document.createElement("h1");
  header.className = "screen-title";
  header.textContent = "Audit loglar";
  container.appendChild(header);

  const listSection = document.createElement("div");
  container.appendChild(listSection);
  listSection.appendChild(skeletonList(5, 60));

  const loadMoreButton = document.createElement("button");
  loadMoreButton.type = "button";
  loadMoreButton.className = "btn btn-out btn-block mt-16";
  loadMoreButton.textContent = "Ko'proq";
  loadMoreButton.style.display = "none";
  container.appendChild(loadMoreButton);

  let nextCursor: string | null | undefined;

  async function load(reset: boolean): Promise<void> {
    try {
      const response = await listAuditLogs(reset ? undefined : (nextCursor ?? undefined));
      if (reset) listSection.replaceChildren();
      if (reset && response.items.length === 0) {
        listSection.appendChild(emptyState("Audit yozuvlari yo'q.", undefined, "check"));
      }
      for (const entry of response.items) {
        const row = document.createElement("div");
        row.className = "card mb-8";

        const top = document.createElement("div");
        top.className = "row-between";
        const action = document.createElement("span");
        action.className = "t-body num";
        action.textContent = entry.action;
        top.appendChild(action);
        const entity = document.createElement("span");
        entity.className = "hint num";
        entity.textContent = `${entry.entity_type}#${entry.entity_id ?? "-"}`;
        top.appendChild(entity);
        row.appendChild(top);

        const meta = document.createElement("div");
        meta.className = "hint mt-8";
        meta.textContent = `${entry.created_at} — actor #${entry.actor_id ?? "-"}`;
        row.appendChild(meta);

        listSection.appendChild(row);
      }
      nextCursor = response.next_cursor;
      loadMoreButton.style.display = nextCursor ? "block" : "none";
    } catch (error) {
      if (reset) listSection.replaceChildren();
      listSection.appendChild(errorState(error, () => void load(reset)));
    }
  }

  loadMoreButton.addEventListener("click", () => void load(false));
  await load(true);
}
