/**
 * API client for InvestIQ backend.
 *
 * - Bearer token auth (access + refresh)
 * - Access token held in memory (via auth store)
 * - Refresh token persisted in expo-secure-store (via auth store)
 * - Response interceptor: on 401, refresh once, replay original + queued requests
 *
 * The client is a singleton `api` instance. The auth store wires token
 * providers into it on boot (see `mobile/src/store/auth.ts`).
 */

import axios, {
  AxiosError,
  AxiosInstance,
  AxiosRequestConfig,
  InternalAxiosRequestConfig,
} from 'axios';
import Constants from 'expo-constants';

type TokenGetter = () => string | null;
type RefreshFn = () => Promise<string | null>;
type LogoutFn = () => Promise<void> | void;

interface QueuedRequest {
  resolve: (token: string) => void;
  reject: (err: unknown) => void;
}

interface RetriableConfig extends InternalAxiosRequestConfig {
  _retry?: boolean;
}

const DEFAULT_BASE_URL =
  (Constants.expoConfig?.extra as { apiBaseUrl?: string } | undefined)?.apiBaseUrl ??
  process.env.EXPO_PUBLIC_API_BASE_URL ??
  'http://localhost:8000';

let getAccessToken: TokenGetter = () => null;
let doRefresh: RefreshFn = async () => null;
let onAuthFailure: LogoutFn = () => {};

let isRefreshing = false;
let waiters: QueuedRequest[] = [];

function drainWaiters(token: string | null, err?: unknown) {
  const pending = waiters;
  waiters = [];
  if (token) {
    for (const w of pending) w.resolve(token);
  } else {
    for (const w of pending) w.reject(err ?? new Error('token refresh failed'));
  }
}

export function configureAuth(opts: {
  getAccessToken: TokenGetter;
  refresh: RefreshFn;
  onAuthFailure: LogoutFn;
}): void {
  getAccessToken = opts.getAccessToken;
  doRefresh = opts.refresh;
  onAuthFailure = opts.onAuthFailure;
}

export const api: AxiosInstance = axios.create({
  baseURL: DEFAULT_BASE_URL,
  timeout: 15_000,
  headers: { 'Content-Type': 'application/json' },
});

api.interceptors.request.use((config) => {
  const token = getAccessToken();
  if (token && config.headers) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

api.interceptors.response.use(
  (resp) => resp,
  async (error: AxiosError) => {
    const original = error.config as RetriableConfig | undefined;
    const status = error.response?.status;

    // Only handle 401 once per request; skip refresh endpoint itself.
    if (
      !original ||
      status !== 401 ||
      original._retry ||
      (original.url && original.url.includes('/api/auth/refresh'))
    ) {
      return Promise.reject(error);
    }

    original._retry = true;

    // If a refresh is already in flight, queue this request.
    if (isRefreshing) {
      return new Promise((resolve, reject) => {
        waiters.push({
          resolve: (token) => {
            if (original.headers) original.headers.Authorization = `Bearer ${token}`;
            resolve(api.request(original));
          },
          reject,
        });
      });
    }

    isRefreshing = true;
    try {
      const newToken = await doRefresh();
      if (!newToken) {
        drainWaiters(null, error);
        await onAuthFailure();
        return Promise.reject(error);
      }
      drainWaiters(newToken);
      if (original.headers) original.headers.Authorization = `Bearer ${newToken}`;
      return api.request(original);
    } catch (refreshErr) {
      drainWaiters(null, refreshErr);
      await onAuthFailure();
      return Promise.reject(refreshErr);
    } finally {
      isRefreshing = false;
    }
  },
);

export async function apiGet<T>(url: string, config?: AxiosRequestConfig): Promise<T> {
  const r = await api.get<T>(url, config);
  return r.data;
}

export async function apiPost<T, B = unknown>(
  url: string,
  body?: B,
  config?: AxiosRequestConfig,
): Promise<T> {
  const r = await api.post<T>(url, body, config);
  return r.data;
}

export const API_BASE_URL = DEFAULT_BASE_URL;
