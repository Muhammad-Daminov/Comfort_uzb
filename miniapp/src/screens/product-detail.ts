import { getProduct, type Variant } from "../api/catalog";
import * as cartState from "../state/cart";
import { priceElement } from "../components/price";
import { skeletonList } from "../components/loading";
import { errorState } from "../components/error-state";
import { signedImage } from "../components/signed-image";
import { setBackButton, setMainButton, hideMainButton, setMainButtonBusy } from "../telegram";
import { navigate } from "../router";
import { uz } from "../locale";

export async function render(container: HTMLElement, params: Record<string, string>): Promise<void> {
  setBackButton(() => navigate("/catalog"));
  const productId = Number(params.id);

  container.appendChild(skeletonList(1, 240));

  let detail;
  try {
    detail = await getProduct(productId);
  } catch (error) {
    container.innerHTML = "";
    container.appendChild(errorState(error, () => void render(container, params)));
    return;
  }

  container.innerHTML = "";

  const gallery = document.createElement("div");
  gallery.className = "card mb-16";
  gallery.style.padding = "0";
  gallery.style.overflow = "hidden";
  const primaryImage = detail.images.find((img) => img.is_primary) ?? detail.images[0];
  gallery.appendChild(
    signedImage(
      (primaryImage as { signed_url?: string } | undefined)?.signed_url ?? null,
      detail.product.name,
      () => void render(container, params), // signed URL expired -> re-fetch the whole product for a fresh one
    ),
  );
  container.appendChild(gallery);

  if (detail.product.brand_name) {
    const brand = document.createElement("div");
    brand.className = "t-brand mb-8";
    brand.textContent = detail.product.brand_name;
    container.appendChild(brand);
  }

  const name = document.createElement("h1");
  name.className = "screen-title";
  name.textContent = detail.product.name;
  container.appendChild(name);

  if (detail.product.description) {
    const description = document.createElement("p");
    description.className = "t-body muted mb-16";
    description.textContent = detail.product.description;
    container.appendChild(description);
  }

  const detailCard = document.createElement("div");
  detailCard.className = "card stack mb-16";

  const variantField = document.createElement("div");
  variantField.className = "field";
  const variantLabel = document.createElement("div");
  variantLabel.className = "field-label";
  variantLabel.textContent = "Variant";
  variantField.appendChild(variantLabel);

  const variantSelect = document.createElement("select");
  for (const variant of detail.variants) {
    const option = document.createElement("option");
    option.value = String(variant.id);
    const available = variant.stock_on_hand - variant.stock_reserved;
    option.disabled = variant.status !== "ACTIVE" || available <= 0;
    option.textContent = `${variant.sku}${option.disabled ? ` (${uz.outOfStock})` : ""}`;
    variantSelect.appendChild(option);
  }
  variantField.appendChild(variantSelect);
  detailCard.appendChild(variantField);

  const priceSection = document.createElement("div");
  priceSection.className = "price-lg";
  detailCard.appendChild(priceSection);

  const availabilitySection = document.createElement("div");
  availabilitySection.className = "hint";
  detailCard.appendChild(availabilitySection);

  container.appendChild(detailCard);

  function selectedVariant(): Variant | undefined {
    return detail!.variants.find((v: Variant) => v.id === Number(variantSelect.value));
  }

  function updateVariantDisplay(): void {
    const variant = selectedVariant();
    priceSection.innerHTML = "";
    if (!variant) return;
    priceSection.appendChild(priceElement(variant.current_price, variant.discount_amount, variant.price));
    const available = variant.stock_on_hand - variant.stock_reserved;
    availabilitySection.textContent = available > 0 ? `${available} dona mavjud` : uz.outOfStock;
    updateMainButton();
  }

  function updateMainButton(): void {
    const variant = selectedVariant();
    if (!variant) {
      hideMainButton();
      return;
    }
    const available = variant.stock_on_hand - variant.stock_reserved;
    if (available <= 0 || variant.status !== "ACTIVE") {
      hideMainButton();
      return;
    }
    setMainButton(uz.addToCart, () => {
      // A failed add (401, 422 unknown variant, offline) used to be an
      // unhandled rejection — nothing happened and nothing was shown.
      setMainButtonBusy(true);
      cartState
        .addItem(variant.id, 1)
        .then(() => navigate("/cart"))
        .catch((error: unknown) => container.appendChild(errorState(error)))
        .finally(() => setMainButtonBusy(false));
    });
  }

  variantSelect.addEventListener("change", updateVariantDisplay);
  updateVariantDisplay();
}
