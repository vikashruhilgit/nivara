/**
 * Auth store (Zustand) + expo-secure-store persistence for the refresh token.
 *
 * Storage rules (per CLAUDE.md):
 *   - Refresh token: expo-secure-store (never AsyncStorage)
 *   - Access token: memory only
 *
 * Flow:
 *   hydrate() is called once at app boot; if a refresh token exists, we call
 *   /api/auth/refresh to get a fresh access token + rotate the refresh token.
 *   The axios client is wired via `configureAuth` to call `refresh` on 401.
 */

import * as SecureStore from 'expo-secure-store';
import { create } from 'zustand';

import { api, apiPost, configureAuth } from '../api/client';

const REFRESH_TOKEN_KEY = 'investiq.refresh_token';

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type?: string;
  expires_in?: number;
}

export interface UserPublic {
  id: string;
  email: string;
  full_name?: string | null;
  locale?: string | null;
}

type Status = 'idle' | 'hydrating' | 'authenticated' | 'unauthenticated';

interface AuthState {
  status: Status;
  accessToken: string | null;
  refreshToken: string | null;
  user: UserPublic | null;
  // actions
  hydrate: () => Promise<void>;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (email: string, password: string, fullName?: string) => Promise<void>;
  signOut: () => Promise<void>;
  refresh: () => Promise<string | null>;
  setUser: (u: UserPublic | null) => void;
}

async function saveRefreshToken(token: string | null): Promise<void> {
  if (token) {
    await SecureStore.setItemAsync(REFRESH_TOKEN_KEY, token);
  } else {
    await SecureStore.deleteItemAsync(REFRESH_TOKEN_KEY);
  }
}

async function loadRefreshToken(): Promise<string | null> {
  return SecureStore.getItemAsync(REFRESH_TOKEN_KEY);
}

export const useAuthStore = create<AuthState>((set, get) => ({
  status: 'idle',
  accessToken: null,
  refreshToken: null,
  user: null,

  async hydrate() {
    set({ status: 'hydrating' });
    const stored = await loadRefreshToken();
    if (!stored) {
      set({ status: 'unauthenticated' });
      return;
    }
    try {
      const pair = await apiPost<TokenPair>('/api/auth/refresh', { refresh_token: stored });
      await saveRefreshToken(pair.refresh_token);
      set({
        accessToken: pair.access_token,
        refreshToken: pair.refresh_token,
        status: 'authenticated',
      });
      // Best-effort: fetch current user.
      try {
        const me = await api.get<UserPublic>('/api/auth/me');
        set({ user: me.data });
      } catch {
        // ignore — still authenticated
      }
    } catch {
      await saveRefreshToken(null);
      set({
        accessToken: null,
        refreshToken: null,
        user: null,
        status: 'unauthenticated',
      });
    }
  },

  async signIn(email, password) {
    const pair = await apiPost<TokenPair>('/api/auth/login', { email, password });
    await saveRefreshToken(pair.refresh_token);
    set({
      accessToken: pair.access_token,
      refreshToken: pair.refresh_token,
      status: 'authenticated',
    });
    try {
      const me = await api.get<UserPublic>('/api/auth/me');
      set({ user: me.data });
    } catch {
      // ignore
    }
  },

  async signUp(email, password, fullName) {
    const pair = await apiPost<TokenPair>('/api/auth/register', {
      email,
      password,
      full_name: fullName,
    });
    await saveRefreshToken(pair.refresh_token);
    set({
      accessToken: pair.access_token,
      refreshToken: pair.refresh_token,
      status: 'authenticated',
    });
    try {
      const me = await api.get<UserPublic>('/api/auth/me');
      set({ user: me.data });
    } catch {
      // ignore
    }
  },

  async signOut() {
    const rt = get().refreshToken;
    if (rt) {
      try {
        await apiPost('/api/auth/logout', { refresh_token: rt });
      } catch {
        // ignore — local sign-out still proceeds
      }
    }
    await saveRefreshToken(null);
    set({
      accessToken: null,
      refreshToken: null,
      user: null,
      status: 'unauthenticated',
    });
  },

  async refresh() {
    const rt = get().refreshToken;
    if (!rt) return null;
    try {
      const pair = await apiPost<TokenPair>('/api/auth/refresh', { refresh_token: rt });
      await saveRefreshToken(pair.refresh_token);
      set({ accessToken: pair.access_token, refreshToken: pair.refresh_token });
      return pair.access_token;
    } catch {
      await saveRefreshToken(null);
      set({
        accessToken: null,
        refreshToken: null,
        user: null,
        status: 'unauthenticated',
      });
      return null;
    }
  },

  setUser(u) {
    set({ user: u });
  },
}));

// Wire axios interceptor to the store. Called once from root layout.
let configured = false;
export function configureAuthClient(): void {
  if (configured) return;
  configured = true;
  configureAuth({
    getAccessToken: () => useAuthStore.getState().accessToken,
    refresh: () => useAuthStore.getState().refresh(),
    onAuthFailure: async () => {
      await useAuthStore.getState().signOut();
    },
  });
}
