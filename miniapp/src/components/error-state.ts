import { ApiError, type ApiErrorKind } from "../api/client";
import { icon as renderIcon } from "./icons";
import { uz } from "../locale";

const MESSAGE_BY_KIND: Record<ApiErrorKind, string> = {
  unauthorized: uz.errorUnauthorized,
  forbidden: uz.errorForbidden,
  not_found: uz.errorNotFound,
  conflict: uz.errorConflict,
  validation: uz.errorValidation,
  server_error: uz.errorServer,
  network: uz.errorNetwork,
};

/** Maps any error (ApiError or unknown) to a safe, generic Uzbek message —
 * never surfaces a stack trace, Postgres error, or internal detail. */
export function messageForError(error: unknown): string {
  if (error instanceof ApiError) return MESSAGE_BY_KIND[error.kind];
  return uz.errorServer;
}

export function errorState(error: unknown, onRetry?: () => void): HTMLElement {
  const wrapper = document.createElement("div");
  wrapper.className = "state";

  const iconEl = renderIcon("alert", 30);
  iconEl.classList.add("state-icon");
  wrapper.appendChild(iconEl);

  const message = document.createElement("p");
  message.className = "state-text error-text";
  message.textContent = messageForError(error);
  wrapper.appendChild(message);

  if (onRetry) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "btn btn-sec";
    button.textContent = uz.retry;
    button.addEventListener("click", onRetry);
    wrapper.appendChild(button);
  }

  return wrapper;
}
