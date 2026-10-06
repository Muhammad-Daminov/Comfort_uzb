/**
 * Imzolangan mahsulot rasmi: lazy yuklash + skeleton (§14.2) va muddati
 * o'tganda qayta so'rash (ADR-13 — muddati o'tgan havola 403/410 qaytaradi,
 * yechim yangi havola so'rash, o'shani qayta urinish emas).
 */
// URLs whose reload has already been attempted once (per page lifetime).
const retriedUrls = new Set<string>();

function brokenPlaceholder(alt: string): HTMLElement {
  const placeholder = document.createElement("div");
  placeholder.className = "skeleton signed-img-placeholder";
  placeholder.setAttribute("aria-label", alt);
  return placeholder;
}

export function signedImage(signedUrl: string | null, alt: string, onExpired?: () => void): HTMLElement {
  if (!signedUrl) {
    const placeholder = document.createElement("div");
    placeholder.className = "skeleton signed-img-placeholder";
    placeholder.setAttribute("aria-label", alt);
    return placeholder;
  }

  const img = document.createElement("img");
  img.className = "signed-img";
  img.src = signedUrl;
  img.alt = alt;
  img.loading = "lazy";
  img.addEventListener("error", () => {
    // Imzolangan havola <img> uchun oddiy yuklash xatosi bo'lib ko'rinadi —
    // statusni o'qib bo'lmaydi. Chaqiruvchining vazifasi: ota resursni
    // qayta so'rab, yangi imzo olish. FAQAT BIR MARTA: fayl diskda yo'q
    // bo'lsa yangi imzo ham xato beradi va qayta so'rov cheksiz aylanardi.
    if (onExpired && !retriedUrls.has(signedUrl)) {
      retriedUrls.add(signedUrl);
      onExpired();
    } else {
      img.replaceWith(brokenPlaceholder(alt));
    }
  });
  return img;
}
