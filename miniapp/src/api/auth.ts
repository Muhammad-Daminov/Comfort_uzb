import { apiRequest } from "./client";

export interface SessionResponse {
  token: string;
  user_id: number;
  role: string;
}

export interface MeResponse {
  id: number;
  telegram_id: number;
  first_name: string | null;
  last_name: string | null;
  username: string | null;
  role: string;
  phone: string | null;
  status: string;
  telegram_notifications_enabled: boolean;
}

export function createSession(initData: string): Promise<SessionResponse> {
  return apiRequest<SessionResponse>("/auth/session", { method: "POST", body: { initData } });
}

export function getMe(): Promise<MeResponse> {
  return apiRequest<MeResponse>("/auth/me");
}

/** §P3B-2: always applies to the caller's own account — `current_user.id`
 * on the backend comes only from the signed session token, never from
 * anything sent here, so there is no `user_id` parameter to (mis)pass. */
export function updateNotificationSettings(enabled: boolean): Promise<MeResponse> {
  return apiRequest<MeResponse>("/auth/me/notification-settings", {
    method: "PATCH",
    body: { telegram_notifications_enabled: enabled },
  });
}
