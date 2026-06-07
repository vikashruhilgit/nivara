/**
 * Surface — the base elevated container primitive.
 *
 * Bakes in the platform-aware "glass" decision:
 *   - SOLID → opaque View (surface color + shadow + hairline border).
 *   - GLASS on iOS (always) and Android static surfaces → real BlurView with a
 *     tinted overlay.
 *   - GLASS on Android list contexts → SIMULATED glass (opaque-ish View at
 *     theme.glass.simulatedAlpha) to avoid scroll jank from BlurView.
 *
 * All colors come from the theme — no raw hex here.
 */

import { BlurView } from 'expo-blur';
import { Platform, StyleSheet, View } from 'react-native';
import type { StyleProp, ViewStyle } from 'react-native';

import { useTheme } from '../theme';
import type { Theme } from '../theme';

export interface SurfaceProps {
  children?: React.ReactNode;
  style?: StyleProp<ViewStyle>;
  /** 'auto' (default) resolves to theme.surfaceStyle. */
  variant?: 'glass' | 'solid' | 'auto';
  elevation?: 'none' | 'sm' | 'md' | 'lg';
  /** 'list' marks the surface as living inside a scrolling list. */
  context?: 'static' | 'list';
  radius?: keyof Theme['radii'];
  bordered?: boolean;
}

function shadowFor(
  theme: Theme,
  elevation: NonNullable<SurfaceProps['elevation']>,
): ViewStyle {
  if (elevation === 'none') return {};
  return theme.shadow[elevation];
}

/**
 * Convert an rgba(...) string to an opaque-ish color at the given alpha.
 * Used only for simulated glass; the source color is itself a token.
 */
function withAlpha(rgba: string, alpha: number): string {
  const match = rgba.match(/^rgba?\(([^)]+)\)$/);
  if (match) {
    const parts = match[1].split(',').map((p) => p.trim());
    const [r, g, b] = parts;
    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
  }
  // Non-rgba (e.g. hex token) — return as-is; opacity handled by overlay.
  return rgba;
}

export function Surface({
  children,
  style,
  variant = 'auto',
  elevation = 'sm',
  context = 'static',
  radius = 'lg',
  bordered = true,
}: SurfaceProps): React.ReactElement {
  const theme = useTheme();
  const effective = variant === 'auto' ? theme.surfaceStyle : variant;
  const borderRadius = theme.radii[radius];

  const borderStyle: ViewStyle = bordered
    ? { borderWidth: StyleSheet.hairlineWidth, borderColor: theme.colors.border }
    : {};

  // ---- SOLID ----------------------------------------------------------------
  if (effective === 'solid') {
    return (
      <View
        style={[
          {
            backgroundColor: theme.colors.surface,
            borderRadius,
            overflow: 'hidden',
          },
          shadowFor(theme, elevation),
          borderStyle,
          style,
        ]}
      >
        {children}
      </View>
    );
  }

  // ---- GLASS (Android list) → simulated -------------------------------------
  const isAndroid = Platform.OS === 'android';
  const useRealBlur = !isAndroid || context === 'static';

  if (!useRealBlur) {
    return (
      <View
        style={[
          {
            backgroundColor: withAlpha(
              theme.colors.surfaceGlassTint,
              theme.glass.simulatedAlpha,
            ),
            borderRadius,
            overflow: 'hidden',
          },
          shadowFor(theme, elevation),
          borderStyle,
          style,
        ]}
      >
        {children}
      </View>
    );
  }

  // ---- GLASS (iOS always, Android static) → real blur -----------------------
  return (
    <View
      style={[
        { borderRadius, overflow: 'hidden' },
        shadowFor(theme, elevation),
        borderStyle,
        style,
      ]}
    >
      <BlurView
        intensity={theme.glass.blurIntensity}
        tint={theme.glass.blurTint}
        experimentalBlurMethod={isAndroid ? 'dimezisBlurView' : undefined}
        style={StyleSheet.absoluteFill}
      />
      <View
        style={[
          StyleSheet.absoluteFill,
          { backgroundColor: theme.colors.surfaceGlassTint },
        ]}
        pointerEvents="none"
      />
      <View>{children}</View>
    </View>
  );
}
