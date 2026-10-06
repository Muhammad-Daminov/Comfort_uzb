import { getMe, updateNotificationSettings } from "../api/auth";
import { skeletonList } from "../components/loading";
import { errorState } from "../components/error-state";
import { icon } from "../components/icons";
import { setBackButton, hideMainButton } from "../telegram";
import { navigate } from "../router";

function sectionHeading(text: string): HTMLElement {
  const heading = document.createElement("div");
  heading.className = "section-title";
  heading.textContent = text;
  return heading;
}

/** Profile + Settings merged into one screen — the TZ names both (§14.1)
 * but gives no distinct content for USER-level Settings beyond profile
 * display, and phone capture is explicitly the bot's job (ADR-2:
 * KeyboardButton(request_contact=True)), not the Mini App's — see the
 * Phase-05 plan's Context for the full reasoning.
 *
 * §P3B-2: Language is display-only — the project has exactly one
 * supported language (Master TZ header, backend/bot/locales/uz.py is the
 * only locale module that exists), so a working switcher would be new
 * i18n architecture the brief explicitly says not to invent. Notification
 * preference is real: it's persisted via `PATCH /auth/me/notification-settings`
 * and enforced by the existing Telegram outbox poller
 * (bot/notifications/poller.py), not a decorative toggle. */
export async function render(container: HTMLElement): Promise<void> {
  container.replaceChildren();
  setBackButton(() => navigate("/home"));
  hideMainButton();

  const header = document.createElement("h1");
  header.className = "screen-title";
  header.textContent = "Profil";
  container.appendChild(header);

  container.appendChild(skeletonList(2, 100));

  try {
    const me = await getMe();
    container.replaceChildren(header);

    const card = document.createElement("div");
    card.className = "card mb-16";

    const nameLine = document.createElement("div");
    nameLine.className = "list-title";
    nameLine.textContent =
      [me.first_name, me.last_name].filter(Boolean).join(" ") || (me.username ?? `#${me.telegram_id}`);
    card.appendChild(nameLine);

    if (me.username) {
      const usernameLine = document.createElement("div");
      usernameLine.className = "list-sub";
      usernameLine.textContent = `@${me.username}`;
      card.appendChild(usernameLine);
    }

    const phoneLine = document.createElement("div");
    phoneLine.className = "t-body mt-12";
    phoneLine.textContent = me.phone ?? "Telefon raqam kiritilmagan";
    card.appendChild(phoneLine);

    if (!me.phone) {
      const hint = document.createElement("div");
      hint.className = "hint";
      hint.textContent = "Telefon raqamni bot orqali yuboring (/start).";
      card.appendChild(hint);
    }

    container.appendChild(card);

    // --- Til (display-only — single supported language) --------------
    container.appendChild(sectionHeading("Til"));
    const languageCard = document.createElement("div");
    languageCard.className = "card mb-16 row-between";
    const languageInfo = document.createElement("div");
    languageInfo.appendChild(icon("globe", 18));
    const languageLabel = document.createElement("span");
    languageLabel.className = "list-title";
    languageLabel.style.marginLeft = "8px";
    languageLabel.textContent = "O'zbekcha";
    languageInfo.appendChild(languageLabel);
    languageInfo.style.display = "flex";
    languageInfo.style.alignItems = "center";
    languageCard.appendChild(languageInfo);
    const languageBadge = document.createElement("span");
    languageBadge.className = "badge";
    languageBadge.textContent = "Yagona til";
    languageCard.appendChild(languageBadge);
    container.appendChild(languageCard);

    // --- Bildirishnomalar ------------------------------------------------
    container.appendChild(sectionHeading("Bildirishnomalar"));
    const notifCard = document.createElement("div");
    notifCard.className = "card mb-16";

    const notifRow = document.createElement("div");
    notifRow.className = "row-between";
    const notifInfo = document.createElement("div");
    notifInfo.style.display = "flex";
    notifInfo.style.alignItems = "center";
    notifInfo.appendChild(icon("bell", 18));
    const notifLabel = document.createElement("span");
    notifLabel.className = "list-title";
    notifLabel.style.marginLeft = "8px";
    notifLabel.textContent = "Telegram orqali xabarnoma";
    notifInfo.appendChild(notifLabel);
    notifRow.appendChild(notifInfo);

    const notifToggle = document.createElement("button");
    notifToggle.type = "button";
    notifToggle.className = "chip";
    notifToggle.setAttribute("aria-pressed", String(me.telegram_notifications_enabled));
    notifToggle.textContent = me.telegram_notifications_enabled ? "Yoqilgan" : "O'chirilgan";
    notifRow.appendChild(notifToggle);
    notifCard.appendChild(notifRow);

    const notifHint = document.createElement("p");
    notifHint.className = "hint mt-12";
    notifHint.textContent =
      "O'chirilganda buyurtma va to'lov holati haqidagi xabarlar ilovada ko'rinishda qoladi, lekin Telegramga yuborilmaydi.";
    notifCard.appendChild(notifHint);

    const notifMessage = document.createElement("div");
    notifCard.appendChild(notifMessage);

    notifToggle.addEventListener("click", () => {
      const next = !(notifToggle.getAttribute("aria-pressed") === "true");
      notifToggle.disabled = true;
      notifMessage.replaceChildren();
      void updateNotificationSettings(next)
        .then((updated) => {
          notifToggle.setAttribute("aria-pressed", String(updated.telegram_notifications_enabled));
          notifToggle.textContent = updated.telegram_notifications_enabled ? "Yoqilgan" : "O'chirilgan";
        })
        .catch((error: unknown) => {
          notifMessage.appendChild(errorState(error));
        })
        .finally(() => {
          notifToggle.disabled = false;
        });
    });

    container.appendChild(notifCard);
  } catch (error) {
    container.replaceChildren(header);
    container.appendChild(errorState(error, () => void render(container)));
  }
}
