/**
 * Mahsulot rasmi va uning o'rnini bosuvchi.
 *
 * Nega alohida komponent: rasm yo'qligi katalogda, savatda va admin
 * ro'yxatida BIR XIL ko'rinishi kerak. Ilgari har joyda boshqacha edi —
 * katalogda emoji, admin da "🖼", savatda umuman hech narsa.
 *
 * O'rin bosuvchi ataylab neytral: fon `--bg`, ustida sidena silueti va
 * nomning bosh harfi. Bir tekis ko'k/yashil to'rtburchak ishlatilmaydi —
 * u rasm BOR degan taassurot beradi, aslida yo'q.
 */

/** Sidena, yon ko'rinish. Ichki SVG — tashqi kutubxona yoki fayl yo'q. */
function seatIcon(): SVGElement {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "1.5");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("class", "pm-icon");

  const paths = [
    "M8.5 2.5h4a1.5 1.5 0 0 1 1.5 1.5v2h-7V4a1.5 1.5 0 0 1 1.5-1.5z", // bosh suyanchig'i
    "M7.6 6.8h5.8a1.6 1.6 0 0 1 1.6 1.5l.5 6.2H5.5l.5-6.2a1.6 1.6 0 0 1 1.6-1.5z", // suyanchiq
    "M4.6 15.2h13.4a1.8 1.8 0 0 1 1.8 1.8v1.6a1.8 1.8 0 0 1-1.8 1.8H6.4a1.8 1.8 0 0 1-1.8-1.8z", // o'tirg'ich
  ];
  for (const d of paths) {
    const path = document.createElementNS(ns, "path");
    path.setAttribute("d", d);
    svg.appendChild(path);
  }
  return svg;
}

/** Nomning birinchi harfi — "Teri sidena" → "T". Emoji yoki bo'sh nomda
 *  hech narsa qaytarmaydi, "?" ko'rsatilmaydi. */
export function initialOf(name: string): string {
  const match = name.trim().match(/\p{L}|\p{N}/u);
  return match ? match[0].toLocaleUpperCase("uz") : "";
}

export function productPlaceholder(name: string): HTMLElement {
  const box = document.createElement("div");
  box.className = "pm-empty";
  box.appendChild(seatIcon());

  const initial = initialOf(name);
  if (initial) {
    const letter = document.createElement("span");
    letter.className = "pm-letter";
    letter.textContent = initial;
    box.appendChild(letter);
  }
  box.setAttribute("role", "img");
  box.setAttribute("aria-label", name ? `${name} — rasm yo'q` : "Rasm yo'q");
  return box;
}

export interface ProductMediaOptions {
  /** Qo'shimcha sinf: `pm-72` (savat), `pm-56` (admin ro'yxati). */
  size?: "sm" | "md" | "full";
  /** Rasm ustiga qo'yiladigan belgilar shu yerga qo'shiladi. */
  onReady?: (box: HTMLElement) => void;
}

const SIZE_CLASS: Record<NonNullable<ProductMediaOptions["size"]>, string> = {
  sm: "pm-56",
  md: "pm-72",
  full: "pm-full",
};

/**
 * Rasm bo'lsa `<img>`, bo'lmasa o'rin bosuvchi. Yuklab bo'lmasa ham
 * o'rin bosuvchiga tushadi — buzilgan rasm belgisi hech qachon
 * ko'rsatilmaydi (imzolangan havola muddati o'tsa ham, ADR-13).
 */
export function productMedia(
  imageUrl: string | null | undefined,
  name: string,
  options: ProductMediaOptions = {},
): HTMLElement {
  const box = document.createElement("div");
  box.className = `pm ${SIZE_CLASS[options.size ?? "full"]}`;

  if (!imageUrl) {
    box.appendChild(productPlaceholder(name));
    options.onReady?.(box);
    return box;
  }

  const img = document.createElement("img");
  img.className = "pm-img";
  img.src = imageUrl;
  img.alt = name;
  // Atribut sifatida — jsdom `loading`/`decoding` xossalarini atributga
  // aks ettirmaydi, brauzerda esa ikkalasi ham bir xil ishlaydi.
  img.setAttribute("loading", "lazy");
  img.setAttribute("decoding", "async");
  img.addEventListener("error", () => {
    img.remove();
    if (!box.querySelector(".pm-empty")) box.insertBefore(productPlaceholder(name), box.firstChild);
  });
  box.appendChild(img);
  options.onReady?.(box);
  return box;
}
