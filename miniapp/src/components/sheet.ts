/** Bottom sheet for a focused decision (variant picker, confirm, filters).
 *  Dismisses on backdrop tap and on Escape; both are removed together so a
 *  closed sheet leaves no listener behind. */
export function openSheet(build: (close: () => void) => HTMLElement): () => void {
  const backdrop = document.createElement("div");
  backdrop.className = "sheet-backdrop";

  const sheet = document.createElement("div");
  sheet.className = "sheet";
  sheet.setAttribute("role", "dialog");
  sheet.setAttribute("aria-modal", "true");

  const handle = document.createElement("div");
  handle.className = "sheet-handle";
  sheet.appendChild(handle);

  function close(): void {
    document.removeEventListener("keydown", onKey);
    backdrop.remove();
    sheet.remove();
  }
  function onKey(event: KeyboardEvent): void {
    if (event.key === "Escape") close();
  }

  sheet.appendChild(build(close));
  backdrop.addEventListener("click", close);
  document.addEventListener("keydown", onKey);
  document.body.appendChild(backdrop);
  document.body.appendChild(sheet);

  return close;
}
