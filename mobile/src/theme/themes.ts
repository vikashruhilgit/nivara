/**
 * Theme composition: assembles a resolved `Theme` from token primitives.
 *
 * `buildTheme` covers all four base combos (glass·dark, glass·light,
 * solid·dark, solid·light) and all three accents. Together with tokens.ts this
 * is the only place raw colors are permitted.
 */

import {
  SPACING_UNIT,
  accentPalette,
  basePalette,
  glassByScheme,
  radii,
  shadowByScheme,
  statusPalette,
  textureByScheme,
  typography,
} from './tokens';
import type {
  AccentName,
  ColorScheme,
  GlassParams,
  SemanticColors,
  SurfaceStyle,
  Theme,
  TextureParams,
} from './types';

function buildColors(scheme: ColorScheme, accent: AccentName): SemanticColors {
  const base = basePalette[scheme];
  const status = statusPalette[scheme];
  const ac = accentPalette[accent][scheme];
  const glassTint = glassByScheme[scheme].tint;

  return {
    background: base.background,
    backgroundElevated: base.backgroundElevated,
    surface: base.surface,
    surfaceAlt: base.surfaceAlt,
    surfaceGlassTint: glassTint,
    textPrimary: base.textPrimary,
    textSecondary: base.textSecondary,
    textTertiary: base.textTertiary,
    textOnAccent: ac.textOnAccent,
    border: base.border,
    borderStrong: base.borderStrong,
    accent: ac.accent,
    accentMuted: ac.accentMuted,
    positive: status.positive.fg,
    positiveBg: status.positive.bg,
    positiveBorder: status.positive.border,
    negative: status.negative.fg,
    negativeBg: status.negative.bg,
    negativeBorder: status.negative.border,
    warning: status.warning.fg,
    warningBg: status.warning.bg,
    warningBorder: status.warning.border,
    neutral: status.neutral.fg,
    neutralBg: status.neutral.bg,
    neutralBorder: status.neutral.border,
    overlay: base.overlay,
    shadow: base.shadow,
  };
}

function buildGlass(scheme: ColorScheme): GlassParams {
  const g = glassByScheme[scheme];
  return {
    blurIntensity: g.blurIntensity,
    blurTint: g.blurTint,
    simulatedAlpha: g.simulatedAlpha,
  };
}

function buildTexture(scheme: ColorScheme): TextureParams {
  const t = textureByScheme[scheme];
  return {
    dotColor: t.dotColor,
    dotRadius: t.dotRadius,
    spacing: t.spacing,
    opacity: t.opacity,
  };
}

export function buildTheme(
  scheme: ColorScheme,
  surface: SurfaceStyle,
  accent: AccentName,
): Theme {
  return {
    scheme,
    isDark: scheme === 'dark',
    surfaceStyle: surface,
    accent,
    colors: buildColors(scheme, accent),
    spacing: (n: number) => n * SPACING_UNIT,
    radii,
    typography,
    shadow: shadowByScheme[scheme],
    glass: buildGlass(scheme),
    texture: buildTexture(scheme),
  };
}
