import { apiRequest } from "./client";

export interface NamedItem {
  id: number;
  name: string;
}

export function listCarBrands(): Promise<{ items: NamedItem[] }> {
  return apiRequest<{ items: NamedItem[] }>("/vehicles/brands");
}

export function listCarModels(carBrandId: number): Promise<{ items: NamedItem[] }> {
  return apiRequest<{ items: NamedItem[] }>(`/vehicles/models?car_brand_id=${carBrandId}`);
}

export function listCarGenerations(carModelId: number): Promise<{ items: NamedItem[] }> {
  return apiRequest<{ items: NamedItem[] }>(`/vehicles/generations?car_model_id=${carModelId}`);
}
