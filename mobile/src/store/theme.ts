/**
 * Theme-preferences store (Zustand) + AsyncStorage persistence.
 *
 * Storage rules (per CLAUDE.md):
 *   - Theme prefs are NON-sensitive → AsyncStorage (NOT expo-secure-store,
 *     which is reserved for auth material).
 *
 * Persists ONLY {mode, surface, accent} under the key 'investiq.theme'.
 * hydrate() is called once at app boot (alongside the auth hydrate).
 */

import AsyncStorage from '@react-native-async-storage/async-storage';
import { create } from 'zustand';

import type { AccentName, SurfaceStyle, ThemeMode } from '../theme/types';

const THEME_PREFS_KEY = 'investiq.theme';

export interface ThemePrefs {
  mode: ThemeMode;
  surface: SurfaceStyle;
  accent: AccentName;
}

const DEFAULT_PREFS: ThemePrefs = {
  mode: 'system',
  surface: 'glass',
  accent: 'indigo',
};

interface ThemeState extends ThemePrefs {
  hydrated: boolean;
  hydrate: () => Promise<void>;
  setMode: (mode: ThemeMode) => void;
  setSurface: (surface: SurfaceStyle) => void;
  setAccent: (accent: AccentName) => void;
}

function isThemeMode(v: unknown): v is ThemeMode {
  return v === 'system' || v === 'light' || v === 'dark';
}

function isSurfaceStyle(v: unknown): v is SurfaceStyle {
  return v === 'glass' || v === 'solid';
}

function isAccentName(v: unknown): v is AccentName {
  return v === 'indigo' || v === 'emerald' || v === 'graphite';
}

function parsePrefs(raw: string | null): ThemePrefs {
  if (!raw) return DEFAULT_PREFS;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== 'object' || parsed === null) return DEFAULT_PREFS;
    const obj = parsed as Record<string, unknown>;
    return {
      mode: isThemeMode(obj.mode) ? obj.mode : DEFAULT_PREFS.mode,
      surface: isSurfaceStyle(obj.surface) ? obj.surface : DEFAULT_PREFS.surface,
      accent: isAccentName(obj.accent) ? obj.accent : DEFAULT_PREFS.accent,
    };
  } catch {
    return DEFAULT_PREFS;
  }
}

async function persistPrefs(prefs: ThemePrefs): Promise<void> {
  try {
    await AsyncStorage.setItem(THEME_PREFS_KEY, JSON.stringify(prefs));
  } catch {
    // best-effort persistence — ignore write failures
  }
}

export const useThemeStore = create<ThemeState>((set, get) => ({
  ...DEFAULT_PREFS,
  hydrated: false,

  async hydrate() {
    let prefs = DEFAULT_PREFS;
    try {
      const raw = await AsyncStorage.getItem(THEME_PREFS_KEY);
      prefs = parsePrefs(raw);
    } catch {
      prefs = DEFAULT_PREFS;
    }
    set({ ...prefs, hydrated: true });
  },

  setMode(mode) {
    set({ mode });
    const { surface, accent } = get();
    void persistPrefs({ mode, surface, accent });
  },

  setSurface(surface) {
    set({ surface });
    const { mode, accent } = get();
    void persistPrefs({ mode, surface, accent });
  },

  setAccent(accent) {
    set({ accent });
    const { mode, surface } = get();
    void persistPrefs({ mode, surface, accent });
  },
}));
