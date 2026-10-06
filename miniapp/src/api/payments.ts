import { apiRequest } from "./client";

export interface PaymentResponse {
  id: number;
  order_id: number;
  amount: number;
  method: string;
  status: string;
  submitted_at?: string;
}

export function submitPayment(orderId: number, idempotencyKey: string): Promise<PaymentResponse> {
  return apiRequest<PaymentResponse>("/payments", { method: "POST", body: { order_id: orderId }, idempotencyKey });
}

export function uploadReceipt(paymentId: number, file: File): Promise<{ id: number; payment_id: number }> {
  const formData = new FormData();
  formData.append("file", file);
  return apiRequest<{ id: number; payment_id: number }>(`/payments/${paymentId}/receipt`, {
    method: "POST",
    body: formData,
    isFormData: true,
  });
}
