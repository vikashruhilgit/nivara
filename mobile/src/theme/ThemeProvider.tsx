/**
 * ThemeProvider + useTheme() — resolves the active `Theme` from the theme
 * prefs store and the OS color scheme, and exposes it via React context.
 */

import { createContext, useContext, useMemo } from 'react';
import { useColorScheme } from 'react-native';

import { useThemeStore } from '../store/theme';
import { buildTheme } from './themes';
import type { ColorScheme, Theme } from './types';

const ThemeContext = createContext<Theme | null>(null);

export function ThemeProvider({
  children,
}: {
  children: React.ReactNode;
}): React.ReactElement {
  const systemScheme = useColorScheme();
  const mode = useThemeStore((s) => s.mode);
  const surface = useThemeStore((s) => s.surface);
  const accent = useThemeStore((s) => s.accent);

  const scheme: ColorScheme =
    mode === 'system' ? (systemScheme ?? 'light') : mode;

  const theme = useMemo(
    () => buildTheme(scheme, surface, accent),
    [scheme, surface, accent],
  );

  return <ThemeContext.Provider value={theme}>{children}</ThemeContext.Provider>;
}

export function useTheme(): Theme {
  const theme = useContext(ThemeContext);
  if (theme === null) {
    throw new Error('useTheme must be used within a <ThemeProvider>');
  }
  return theme;
}
