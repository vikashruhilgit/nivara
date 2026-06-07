/**
 * Theme composition tests — verify buildTheme produces distinct, correct
 * values across scheme, surface, and accent dimensions.
 */

import { buildTheme } from '../theme';

describe('buildTheme', () => {
  it('returns distinct background colors for light vs dark', () => {
    const light = buildTheme('light', 'glass', 'indigo');
    const dark = buildTheme('dark', 'glass', 'indigo');
    expect(light.colors.background).not.toBe(dark.colors.background);
    expect(light.isDark).toBe(false);
    expect(dark.isDark).toBe(true);
  });

  it('switching surface glass -> solid changes surfaceStyle', () => {
    const glass = buildTheme('light', 'glass', 'indigo');
    const solid = buildTheme('light', 'solid', 'indigo');
    expect(glass.surfaceStyle).toBe('glass');
    expect(solid.surfaceStyle).toBe('solid');
  });

  it('an accent change changes colors.accent', () => {
    const indigo = buildTheme('light', 'glass', 'indigo');
    const emerald = buildTheme('light', 'glass', 'emerald');
    expect(indigo.colors.accent).not.toBe(emerald.colors.accent);
    expect(indigo.accent).toBe('indigo');
    expect(emerald.accent).toBe('emerald');
  });

  it('exposes spacing, radii, and typography scales', () => {
    const theme = buildTheme('light', 'glass', 'indigo');
    expect(theme.spacing(4)).toBe(16);
    expect(theme.radii.pill).toBe(999);
    expect(theme.typography.body.fontSize).toBeGreaterThan(0);
  });
});
