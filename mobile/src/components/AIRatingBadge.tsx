import React from 'react';
import { StyleSheet, Text, View } from 'react-native';

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

function colorFor(action: RecommendationAction): string {
  switch (action) {
    case 'strong_buy':
    case 'buy':
      return '#1a7f37';
    case 'sell':
    case 'strong_sell':
      return '#cf222e';
    case 'hold':
    default:
      return '#57606a';
  }
}

export function AIRatingBadge({
  action,
  confidence,
}: AIRatingBadgeProps): React.ReactElement | null {
  if (action === null) {
    return null;
  }
  const label = ACTION_LABELS[action];
  const color = colorFor(action);
  const text =
    confidence !== null && confidence !== undefined
      ? `${label} ${Math.round(confidence)}%`
      : label;
  return (
    <View style={[styles.badge, { backgroundColor: color }]}>
      <Text style={styles.text}>{text}</Text>
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
    color: '#ffffff',
    fontSize: 11,
    fontWeight: '600',
  },
});
