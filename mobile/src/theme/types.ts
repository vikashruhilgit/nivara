/**
 * Theme type contract for the InvestIQ mobile app.
 *
 * These types are the public API consumed by UI primitives and every screen.
 * Names here are a hard contract — change with care (downstream depends on them).
 */

export type ThemeMode = 'system' | 'light' | 'dark';
export type SurfaceStyle = 'glass' | 'solid';
export type AccentName = 'indigo' | 'emerald' | 'graphite';
export type ColorScheme = 'light' | 'dark'; // resolved scheme

export interface SemanticColors {
  background: string;
  backgroundElevated: string;
  surface: string; // opaque card surface
  surfaceAlt: string; // subtle alt surface (inputs, chips)
  surfaceGlassTint: string; // rgba tint laid over blur / simulated glass
  textPrimary: string;
  textSecondary: string;
  textTertiary: string;
  textOnAccent: string; // text/icon on an accent-filled button
  border: string;
  borderStrong: string;
  accent: string;
  accentMuted: string; // low-alpha accent bg (selected chips, tints)
  positive: string;
  positiveBg: string;
  positiveBorder: string;
  negative: string;
  negativeBg: string;
  negativeBorder: string;
  warning: string;
  warningBg: string;
  warningBorder: string;
  neutral: string;
  neutralBg: string;
  neutralBorder: string;
  overlay: string; // modal scrim rgba
  shadow: string; // shadow color
}

export interface GlassParams {
  blurIntensity: number; // expo-blur intensity for static/hero surfaces
  blurTint: 'light' | 'dark' | 'default';
  simulatedAlpha: number; // fallback surface alpha for list items / Android lists (0..1)
}

export interface TextureParams {
  dotColor: string; // rgba — very subtle
  dotRadius: number; // dot radius in px
  spacing: number; // grid spacing in px
  opacity: number; // overall texture-layer opacity (0..1, low)
}

export interface Radii {
  sm: number;
  md: number;
  lg: number;
  xl: number;
  pill: number;
}

export interface ShadowStyle {
  shadowColor: string;
  shadowOffset: { width: number; height: number };
  shadowOpacity: number;
  shadowRadius: number;
  elevation: number;
}

export interface Theme {
  scheme: ColorScheme;
  isDark: boolean;
  surfaceStyle: SurfaceStyle;
  accent: AccentName;
  colors: SemanticColors;
  spacing: (n: number) => number; // n * 4 base unit
  radii: Radii;
  typography: {
    h1: { fontSize: number; fontWeight: '700'; lineHeight: number };
    h2: { fontSize: number; fontWeight: '700'; lineHeight: number };
    title: { fontSize: number; fontWeight: '700'; lineHeight: number };
    body: { fontSize: number; fontWeight: '400'; lineHeight: number };
    label: { fontSize: number; fontWeight: '600'; lineHeight: number };
    caption: { fontSize: number; fontWeight: '500'; lineHeight: number };
  };
  shadow: { sm: ShadowStyle; md: ShadowStyle; lg: ShadowStyle };
  glass: GlassParams;
  texture: TextureParams;
}
