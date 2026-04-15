import React from 'react';
import { StyleSheet, Text, View } from 'react-native';

import type { PortfolioSummary as PortfolioSummaryData } from '../hooks/usePortfolio';
import { formatCurrency } from '../lib/format';
import { PnLDisplay } from './PnLDisplay';

export interface PortfolioSummaryProps {
  summary: PortfolioSummaryData | undefined;
}

export function PortfolioSummary({
  summary,
}: PortfolioSummaryProps): React.ReactElement {
  if (!summary) {
    return (
      <View style={styles.header}>
        <Text style={styles.muted}>Summary unavailable</Text>
      </View>
    );
  }

  return (
    <View style={styles.header}>
      <Text style={styles.totalLabel}>Total value ({summary.currency})</Text>
      <Text style={styles.totalValue}>
        {formatCurrency(summary.total_value, summary.currency)}
      </Text>
      <PnLDisplay
        amount={summary.day_change}
        pct={summary.day_change_pct}
        currency={summary.currency}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  header: { marginBottom: 16 },
  totalLabel: { color: '#57606a', fontSize: 14 },
  totalValue: { fontSize: 32, fontWeight: '700', marginTop: 4 },
  muted: { color: '#57606a', fontSize: 13, marginTop: 2 },
});
