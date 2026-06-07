import React from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { useTheme } from '../theme';
import type { Theme } from '../theme';

export type FreshnessLevel = 'fresh' | 'aging' | 'stale' | 'suppressed';

export interface FreshnessBadgeProps {
  level: FreshnessLevel;
}

interface BadgeStyle {
  bg: string;
  fg: string;
  border: string;
  label: string;
}

function styleFor(theme: Theme, level: FreshnessLevel): BadgeStyle {
  const c = theme.colors;
  switch (level) {
    case 'fresh':
      return { bg: c.positiveBg, fg: c.positive, border: c.positiveBorder, label: 'Fresh' };
    case 'aging':
      return { bg: c.neutralBg, fg: c.neutral, border: c.neutralBorder, label: 'Aging' };
    case 'stale':
      return { bg: c.warningBg, fg: c.warning, border: c.warningBorder, label: 'Stale data' };
    case 'suppressed':
      return { bg: c.negativeBg, fg: c.negative, border: c.negativeBorder, label: 'Suppressed' };
  }
}

export function FreshnessBadge({ level }: FreshnessBadgeProps): React.ReactElement {
  const theme = useTheme();
  const s = styleFor(theme, level);
  return (
    <View
      style={[styles.pill, { backgroundColor: s.bg, borderColor: s.border }]}
      accessibilityLabel={`Data freshness: ${s.label}`}
    >
      <Text style={[styles.text, { color: s.fg }]}>{s.label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  pill: {
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 999,
    borderWidth: StyleSheet.hairlineWidth,
    alignSelf: 'flex-start',
  },
  text: {
    fontSize: 11,
    fontWeight: '700',
    letterSpacing: 0.3,
  },
});
