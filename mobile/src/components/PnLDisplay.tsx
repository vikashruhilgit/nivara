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
  // Defensive: callers may pass undefined/NaN (e.g. fields the backend omits),
  // so coerce to finite numbers rather than crashing on `.toFixed`.
  const safeAmount = Number.isFinite(amount) ? amount : 0;
  const safePct = Number.isFinite(pct) ? pct : 0;
  const gain = safeAmount >= 0;
  const sign = gain ? '+' : '';
  return (
    <Text
      style={[
        compact ? styles.compact : styles.base,
        gain ? styles.gain : styles.loss,
      ]}
    >
      {sign}
      {formatCurrency(safeAmount, currency)} ({sign}
      {safePct.toFixed(2)}%)
    </Text>
  );
}

const styles = StyleSheet.create({
  base: { fontSize: 14, marginTop: 4 },
  compact: { fontSize: 13, marginTop: 2 },
  gain: { color: '#1a7f37' },
  loss: { color: '#cf222e' },
});
