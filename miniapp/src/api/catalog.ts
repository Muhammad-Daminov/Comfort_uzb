import { apiRequest } from "./client";

export interface ProductListItem {
  id: number;
  name: string;
  brand_id: number;
  status: string;
  created_at: string;
  min_price: number;
  total_available: number;
  popularity: number;
  /** Signed URL of the product's primary image (ADR-13), or null if the
   *  product has no image yet. Signed server-side by GET /catalog/products
   *  exactly like the detail endpoint's images[].signed_url. */
  primary_image_url: string | null;
  /** Product brand, or null when the brand row has been archived — the
   *  product itself stays in the catalogue either way. */
  brand_name: string | null;
  /** Pre-discount price of the cheapest-after-discount variant; null when no
   *  discount applies. `min_price` is already the discounted price. */
  old_price: number | null;
  /** Up to two compatibilities, newest first: "Nexia 3 2016–2024". */
  fitment_summary: string | null;
  /** Total compatibilities, so the card can show how many were not listed. */
  fitment_total: number;
}

export interface ProductListResponse {
  items: ProductListItem[];
  next_cursor: string | null;
}

export interface ProductListFilters {
  car_brand_id?: number;
  car_model_id?: number;
  brand_id?: number;
  color_id?: number;
  price_min?: number;
  price_max?: number;
  in_stock_only?: boolean;
  sort?: "newest" | "price_asc" | "price_desc" | "popular";
  cursor?: string;
  limit?: number;
}

export interface Variant {
  id: number;
  product_id: number;
  sku: string;
  color_id: number | null;
  material: string | null;
  price: number;
  required_initial_payment: number;
  stock_on_hand: number;
  stock_reserved: number;
  status: string;
  current_price: number;
  discount_amount: number;
}

export interface ProductImage {
  id: number;
  storage_path: string;
  sort_order: number;
  is_primary: boolean;
  width: number | null;
  height: number | null;
}

export interface ProductDetailResponse {
  product: {
    id: number;
    name: string;
    description: string | null;
    brand_id: number;
    brand_name: string;
    status: string;
    source: string;
    product_type: "SIDENA" | "SIDENA_COVER" | null;
  };
  variants: Variant[];
  images: ProductImage[];
}

export interface FiltersResponse {
  brands: { id: number; name: string }[];
  colors: { id: number; name: string; hex_code: string | null }[];
  car_brands: { id: number; name: string }[];
}

function toQueryString(params: object): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params as Record<string, unknown>)) {
    if (value !== undefined && value !== null && value !== "") query.set(key, String(value));
  }
  const asString = query.toString();
  return asString ? `?${asString}` : "";
}

export function listProducts(filters: ProductListFilters = {}): Promise<ProductListResponse> {
  return apiRequest<ProductListResponse>(`/catalog/products${toQueryString(filters)}`);
}

export function getProduct(productId: number): Promise<ProductDetailResponse> {
  return apiRequest<ProductDetailResponse>(`/catalog/products/${productId}`);
}

export function searchProducts(query: string, signal?: AbortSignal): Promise<{ items: ProductListItem[] }> {
  return apiRequest<{ items: ProductListItem[] }>(`/catalog/search${toQueryString({ q: query })}`, { signal });
}

export function getFilters(): Promise<FiltersResponse> {
  return apiRequest<FiltersResponse>("/catalog/filters");
}
