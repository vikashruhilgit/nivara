import React from 'react';
import { StyleSheet, Text, View } from 'react-native';

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

function styleFor(level: FreshnessLevel): BadgeStyle {
  switch (level) {
    case 'fresh':
      return { bg: '#dafbe1', fg: '#1a7f37', border: '#1a7f37', label: 'Fresh' };
    case 'aging':
      return { bg: '#eaeef2', fg: '#57606a', border: '#d0d7de', label: 'Aging' };
    case 'stale':
      return { bg: '#fff8c5', fg: '#9a6700', border: '#d4a72c', label: 'Stale data' };
    case 'suppressed':
      return { bg: '#ffebe9', fg: '#cf222e', border: '#cf222e', label: 'Suppressed' };
  }
}

export function FreshnessBadge({ level }: FreshnessBadgeProps): React.ReactElement {
  const s = styleFor(level);
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
