export interface InputOptions {
  type?: "text" | "number" | "tel" | "search" | "file";
  placeholder?: string;
  value?: string;
  accept?: string;
  numeric?: boolean;
}

/** Labelled field. Returns both the wrapper (to append) and the control (to
 *  read), so a screen never has to reach into the DOM to find its own input.
 *
 *  `scroll-margin` via .keyboard-safe on the wrapper: iOS shrinks the visual
 *  viewport for the keyboard instead of resizing the page, so a focused
 *  field near the bottom can end up hidden behind it. */
export function field(
  labelText: string,
  options: InputOptions = {},
): { wrapper: HTMLElement; input: HTMLInputElement; setError: (message: string | null) => void } {
  const wrapper = document.createElement("div");
  wrapper.className = "field keyboard-safe";

  const label = document.createElement("label");
  label.className = "field-label";
  label.textContent = labelText;
  wrapper.appendChild(label);

  const input = document.createElement("input");
  input.type = options.type ?? "text";
  if (options.placeholder) input.placeholder = options.placeholder;
  if (options.value !== undefined) input.value = options.value;
  if (options.accept) input.accept = options.accept;
  if (options.numeric) input.inputMode = "numeric";
  label.appendChild(input);

  const error = document.createElement("div");
  error.className = "field-error";
  wrapper.appendChild(error);

  input.addEventListener("focus", () => {
    // Give the browser a frame to lay out the keyboard first.
    setTimeout(() => input.scrollIntoView({ block: "center", behavior: "smooth" }), 150);
  });

  return {
    wrapper,
    input,
    setError(message: string | null) {
      error.textContent = message ?? "";
    },
  };
}

/** Labelled <select> — same shape as `field` for consistency. */
export function selectField(
  labelText: string,
  entries: Array<{ value: string; label: string }>,
): { wrapper: HTMLElement; select: HTMLSelectElement } {
  const wrapper = document.createElement("div");
  wrapper.className = "field keyboard-safe";

  const label = document.createElement("label");
  label.className = "field-label";
  label.textContent = labelText;
  wrapper.appendChild(label);

  const select = document.createElement("select");
  for (const entry of entries) {
    const option = document.createElement("option");
    option.value = entry.value;
    option.textContent = entry.label;
    select.appendChild(option);
  }
  label.appendChild(select);

  return { wrapper, select };
}
