import { icon } from "./icons";
import { closeMiniApp } from "../telegram";

/** §P2-1: AI Assistant lives in the bot chat (text/voice/image), not a
 *  Mini App screen — closing the Mini App returns the admin to the exact
 *  chat it was opened from (telegram.ts::closeMiniApp), no bot
 *  username/deep-link needed. Shared by admin/dashboard.ts and
 *  owner/dashboard.ts — both already gate rendering this to ADMIN/OWNER,
 *  never USER. */
export function aiAssistantCard(): HTMLElement {
  const card = document.createElement("button");
  card.type = "button";
  card.className = "card card-tap hero mb-16";
  card.style.textAlign = "left";
  card.style.width = "100%";
  card.addEventListener("click", () => closeMiniApp());

  const top = document.createElement("div");
  top.className = "row mb-8";
  top.style.color = "var(--acc)";
  top.appendChild(icon("sparkle", 20));
  const eyebrow = document.createElement("span");
  eyebrow.className = "hero-eyebrow";
  eyebrow.style.margin = "0";
  eyebrow.textContent = "AI Assistant";
  top.appendChild(eyebrow);
  card.appendChild(top);

  const title = document.createElement("div");
  title.className = "hero-title";
  title.style.fontSize = "19px";
  title.textContent = "Botda matn, ovoz yoki rasm bilan boshqaring";
  card.appendChild(title);

  const sub = document.createElement("p");
  sub.className = "hero-sub";
  sub.textContent = "Mahsulot qo'shish, stok o'zgartirish va statistika — botga qayting va yozing.";
  card.appendChild(sub);

  return card;
}
