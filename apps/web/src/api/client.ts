import axios from "axios";
import { authStore } from "../lib/auth";

const baseURL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

export const api = axios.create({ baseURL });

api.interceptors.request.use((config) => {
  const token = authStore.get();
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

api.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err?.response?.status === 401) {
      // /v1/* 는 API Key 인증 경로이므로 JWT 세션과 무관 — 로그아웃하지 않는다.
      const url: string = err?.config?.url || "";
      const isOpenAIRoute = url.startsWith("/v1/") || url === "/v1";
      if (!isOpenAIRoute) {
        authStore.clear();
        if (location.pathname !== "/") location.href = "/";
      }
    }
    return Promise.reject(err);
  }
);

export type Role = "general" | "admin";

export type Me = {
  id: string;
  email: string;
  name: string;
  role: Role;
  // 단위는 크레딧(토큰 아님)
  usage_limit: number;
  current_usage: number;
  percent_used: number;
  max_concurrent: number;
};

export type KeyInfo = {
  prefix: string;
  expires_at: string;
  created_at: string;
};

export type IssuedKey = {
  api_key: string;
  prefix: string;
  expires_at: string;
};

export type UsageToday = {
  used: number;
  limit: number;
  percent_used: number;
  reset_at: string;
};
export type UsageHistoryItem = {
  date: string;
  credits: number;
  total_tokens: number;
  request_count: number;
};

export type AdminUserItem = {
  id: string;
  email: string;
  name: string;
  role: Role;
  // 단위는 크레딧(토큰 아님)
  usage_limit: number;
  current_usage: number;
  percent_used: number;
  max_concurrent: number;
  api_key_prefix: string | null;
  api_key_expires_at: string | null;
  created_at: string;
};

export type AdminUserUpdate = {
  usage_limit?: number;
  current_usage?: number;
  max_concurrent?: number;
  role?: Role;
};

export type AdminTopUser = {
  id: string;
  name: string;
  email: string;
  current_usage: number;
  usage_limit: number;
  percent_used: number;
};

export type AdminStats = {
  total_users: number;
  admin_count: number;
  active_users_today: number;
  // 단위는 크레딧(토큰 아님)
  total_credits_today: number;
  total_requests_today: number;
  total_tokens_today: number;
  daily_history: UsageHistoryItem[];
  top_users: AdminTopUser[];
};
