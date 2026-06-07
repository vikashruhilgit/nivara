/**
 * Public barrel for the theme module. Downstream imports from here, e.g.:
 *   import { useTheme, type Theme } from '../../src/theme';
 */

export { ThemeProvider, useTheme } from './ThemeProvider';
export { buildTheme } from './themes';
export { useThemeStore, type ThemePrefs } from '../store/theme';
export type {
  AccentName,
  ColorScheme,
  GlassParams,
  Radii,
  SemanticColors,
  ShadowStyle,
  SurfaceStyle,
  TextureParams,
  Theme,
  ThemeMode,
} from './types';
