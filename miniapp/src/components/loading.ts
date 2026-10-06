/** Generic skeleton list. Kept as-is signature-wise (many screens call it);
 *  spacing now comes from the stylesheet instead of inline styles. */
export function skeletonList(count: number, height = 80): HTMLElement {
  const wrapper = document.createElement("div");
  wrapper.className = "stack-8";
  for (let i = 0; i < count; i++) {
    const el = document.createElement("div");
    el.className = "skeleton skeleton-card";
    el.style.height = `${height}px`;
    wrapper.appendChild(el);
  }
  return wrapper;
}

export { skeletonBlock, skeletonProductGrid } from "./skeleton";
