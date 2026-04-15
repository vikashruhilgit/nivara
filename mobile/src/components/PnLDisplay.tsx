import React from 'react';
import { StyleSheet, Text } from 'react-native';

import { formatCurrency } from '../lib/format';

export interface PnLDisplayProps {
  amount: number;
  pct: number;
  currency: string;
  compact?: boolean;
}

export function PnLDisplay({
  amount,
  pct,
  currency,
  compact = false,
}: PnLDisplayProps): React.ReactElement {
  const gain = amount >= 0;
  const sign = gain ? '+' : '';
  return (
    <Text
      style={[
        compact ? styles.compact : styles.base,
        gain ? styles.gain : styles.loss,
      ]}
    >
      {sign}
      {formatCurrency(amount, currency)} ({sign}
      {pct.toFixed(2)}%)
    </Text>
  );
}

const styles = StyleSheet.create({
  base: { fontSize: 14, marginTop: 4 },
  compact: { fontSize: 13, marginTop: 2 },
  gain: { color: '#1a7f37' },
  loss: { color: '#cf222e' },
});
