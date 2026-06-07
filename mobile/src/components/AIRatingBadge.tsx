import React from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { useTheme } from '../theme';
import type { Theme } from '../theme';

export type RecommendationAction =
  | 'strong_buy'
  | 'buy'
  | 'hold'
  | 'sell'
  | 'strong_sell';

export interface AIRatingBadgeProps {
  action: RecommendationAction | null;
  confidence: number | null;
}

const ACTION_LABELS: Record<RecommendationAction, string> = {
  strong_buy: 'Strong Buy',
  buy: 'Buy',
  hold: 'Hold',
  sell: 'Sell',
  strong_sell: 'Strong Sell',
};

/** Background + on-color for each action, drawn from semantic tokens. */
function colorsFor(
  theme: Theme,
  action: RecommendationAction,
): { bg: string; fg: string } {
  const c = theme.colors;
  switch (action) {
    case 'strong_buy':
    case 'buy':
      return { bg: c.positive, fg: c.textOnAccent };
    case 'sell':
    case 'strong_sell':
      return { bg: c.negative, fg: c.textOnAccent };
    case 'hold':
    default:
      return { bg: c.neutral, fg: c.textOnAccent };
  }
}

export function AIRatingBadge({
  action,
  confidence,
}: AIRatingBadgeProps): React.ReactElement | null {
  const theme = useTheme();
  if (action === null) {
    return null;
  }
  const label = ACTION_LABELS[action];
  const { bg, fg } = colorsFor(theme, action);
  const text =
    confidence !== null && confidence !== undefined
      ? `${label} ${Math.round(confidence)}%`
      : label;
  return (
    <View style={[styles.badge, { backgroundColor: bg }]}>
      <Text style={[styles.text, { color: fg }]}>{text}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  badge: {
    alignSelf: 'flex-end',
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 10,
    marginTop: 4,
  },
  text: {
    fontSize: 11,
    fontWeight: '600',
  },
});
