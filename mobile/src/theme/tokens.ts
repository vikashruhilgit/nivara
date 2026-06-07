/**
 * Design-token primitives for the InvestIQ theme.
 *
 * This file (and themes.ts) are the ONLY places raw hex/rgba colors are allowed.
 * Everything downstream consumes the composed semantic `Theme` instead.
 */

import type {
  AccentName,
  ColorScheme,
  Radii,
  ShadowStyle,
} from './types';

// ---------------------------------------------------------------------------
// Base palette (per scheme)
// ---------------------------------------------------------------------------

export interface BasePalette {
  background: string;
  backgroundElevated: string;
  surface: string;
  surfaceAlt: string;
  textPrimary: string;
  textSecondary: string;
  textTertiary: string;
  border: string;
  borderStrong: string;
  overlay: string;
  shadow: string;
}

export const basePalette: Record<ColorScheme, BasePalette> = {
  light: {
    background: '#f6f8fa',
    backgroundElevated: '#ffffff',
    surface: '#ffffff',
    surfaceAlt: '#f6f8fa',
    textPrimary: '#1f2328',
    textSecondary: '#57606a',
    textTertiary: '#8c959f',
    border: '#d0d7de',
    borderStrong: '#8c959f',
    overlay: 'rgba(31, 35, 40, 0.45)',
    shadow: '#1f2328',
  },
  dark: {
    background: '#0d1117',
    backgroundElevated: '#161b22',
    surface: '#161b22',
    surfaceAlt: '#21262d',
    textPrimary: '#e6edf3',
    textSecondary: '#8b949e',
    textTertiary: '#6e7681',
    border: '#30363d',
    borderStrong: '#484f58',
    overlay: 'rgba(1, 4, 9, 0.65)',
    shadow: '#010409',
  },
};

// ---------------------------------------------------------------------------
// Status palette (per scheme) — tuned fg/bg/border for WCAG AA
// ---------------------------------------------------------------------------

export interface StatusEntry {
  fg: string;
  bg: string;
  border: string;
}

export interface StatusPalette {
  positive: StatusEntry;
  negative: StatusEntry;
  warning: StatusEntry;
  neutral: StatusEntry;
}

export const statusPalette: Record<ColorScheme, StatusPalette> = {
  light: {
    positive: { fg: '#1a7f37', bg: '#dafbe1', border: '#1a7f37' },
    negative: { fg: '#cf222e', bg: '#ffebe9', border: '#cf222e' },
    warning: { fg: '#9a6700', bg: '#fff8c5', border: '#d4a72c' },
    neutral: { fg: '#57606a', bg: '#eaeef2', border: '#d0d7de' },
  },
  dark: {
    positive: { fg: '#3fb950', bg: 'rgba(63, 185, 80, 0.15)', border: '#238636' },
    negative: { fg: '#f85149', bg: 'rgba(248, 81, 73, 0.15)', border: '#da3633' },
    warning: { fg: '#d29922', bg: 'rgba(210, 153, 34, 0.15)', border: '#9e6a03' },
    neutral: { fg: '#8b949e', bg: '#21262d', border: '#30363d' },
  },
};

// ---------------------------------------------------------------------------
// Accent palette (per accent, per scheme)
// ---------------------------------------------------------------------------

export interface AccentEntry {
  accent: string;
  accentMuted: string; // low-alpha accent bg
  textOnAccent: string;
}

export const accentPalette: Record<AccentName, Record<ColorScheme, AccentEntry>> = {
  indigo: {
    light: {
      accent: '#4f46e5',
      accentMuted: 'rgba(79, 70, 229, 0.12)',
      textOnAccent: '#ffffff',
    },
    dark: {
      accent: '#7c83ff',
      accentMuted: 'rgba(124, 131, 255, 0.16)',
      textOnAccent: '#ffffff',
    },
  },
  emerald: {
    light: {
      accent: '#059669',
      accentMuted: 'rgba(5, 150, 105, 0.12)',
      textOnAccent: '#ffffff',
    },
    dark: {
      accent: '#34d399',
      accentMuted: 'rgba(52, 211, 153, 0.16)',
      textOnAccent: '#062b21',
    },
  },
  graphite: {
    light: {
      accent: '#475569',
      accentMuted: 'rgba(71, 85, 105, 0.12)',
      textOnAccent: '#ffffff',
    },
    dark: {
      accent: '#94a3b8',
      accentMuted: 'rgba(148, 163, 184, 0.16)',
      textOnAccent: '#0d1117',
    },
  },
};

// ---------------------------------------------------------------------------
// Glass params (per scheme) — surfaceGlassTint composed in themes.ts
// ---------------------------------------------------------------------------

export const glassByScheme: Record<
  ColorScheme,
  { blurIntensity: number; blurTint: 'light' | 'dark'; simulatedAlpha: number; tint: string }
> = {
  light: {
    blurIntensity: 40,
    blurTint: 'light',
    simulatedAlpha: 0.7,
    tint: 'rgba(255, 255, 255, 0.7)',
  },
  dark: {
    blurIntensity: 40,
    blurTint: 'dark',
    simulatedAlpha: 0.55,
    tint: 'rgba(22, 27, 34, 0.55)',
  },
};

// ---------------------------------------------------------------------------
// Texture params (per scheme) — subtle dot grid, never reduces text contrast
// ---------------------------------------------------------------------------

export const textureByScheme: Record<
  ColorScheme,
  { dotColor: string; dotRadius: number; spacing: number; opacity: number }
> = {
  light: {
    dotColor: 'rgba(31, 35, 40, 0.04)',
    dotRadius: 1,
    spacing: 22,
    opacity: 1,
  },
  dark: {
    dotColor: 'rgba(230, 237, 243, 0.05)',
    dotRadius: 1,
    spacing: 22,
    opacity: 1,
  },
};

// ---------------------------------------------------------------------------
// Scale primitives (scheme-independent)
// ---------------------------------------------------------------------------

export const SPACING_UNIT = 4;

export const radii: Radii = {
  sm: 6,
  md: 10,
  lg: 16,
  xl: 24,
  pill: 999,
};

export const shadowByScheme: Record<
  ColorScheme,
  { sm: ShadowStyle; md: ShadowStyle; lg: ShadowStyle }
> = {
  light: {
    sm: {
      shadowColor: basePalette.light.shadow,
      shadowOffset: { width: 0, height: 1 },
      shadowOpacity: 0.06,
      shadowRadius: 2,
      elevation: 1,
    },
    md: {
      shadowColor: basePalette.light.shadow,
      shadowOffset: { width: 0, height: 4 },
      shadowOpacity: 0.1,
      shadowRadius: 8,
      elevation: 4,
    },
    lg: {
      shadowColor: basePalette.light.shadow,
      shadowOffset: { width: 0, height: 12 },
      shadowOpacity: 0.16,
      shadowRadius: 24,
      elevation: 12,
    },
  },
  dark: {
    sm: {
      shadowColor: basePalette.dark.shadow,
      shadowOffset: { width: 0, height: 1 },
      shadowOpacity: 0.3,
      shadowRadius: 2,
      elevation: 1,
    },
    md: {
      shadowColor: basePalette.dark.shadow,
      shadowOffset: { width: 0, height: 4 },
      shadowOpacity: 0.4,
      shadowRadius: 8,
      elevation: 4,
    },
    lg: {
      shadowColor: basePalette.dark.shadow,
      shadowOffset: { width: 0, height: 12 },
      shadowOpacity: 0.5,
      shadowRadius: 24,
      elevation: 12,
    },
  },
};

export const typography = {
  h1: { fontSize: 32, fontWeight: '700', lineHeight: 38 },
  h2: { fontSize: 26, fontWeight: '700', lineHeight: 32 },
  title: { fontSize: 20, fontWeight: '700', lineHeight: 26 },
  body: { fontSize: 16, fontWeight: '400', lineHeight: 22 },
  label: { fontSize: 14, fontWeight: '600', lineHeight: 18 },
  caption: { fontSize: 12, fontWeight: '500', lineHeight: 16 },
} as const;
