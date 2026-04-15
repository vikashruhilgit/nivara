/**
 * BenchmarkComparison — displays a single benchmark alongside the user's
 * portfolio return for the same period.
 *
 * Purely presentational. Parent supplies the numbers (fetched via
 * `useBenchmark` + portfolio data). Arrows indicate direction; a stale badge
 * appears when the benchmark data provider flagged the series as stale.
 */

import React from 'react';
import { StyleSheet, Text, View } from 'react-native';

export interface BenchmarkComparisonProps {
  benchmarkSymbol: string;
  benchmarkLabel: string;
  benchmarkReturnPct: number;
  portfolioReturnPct: number;
  currency: string;
  periodDays: number;
  stale?: boolean;
}

function formatPct(pct: number): string {
  const sign = pct >= 0 ? '+' : '';
  return `${sign}${pct.toFixed(2)}%`;
}

function arrow(pct: number): string {
  if (pct > 0) return '↑';
  if (pct < 0) return '↓';
  return '·';
}

export function BenchmarkComparison({
  benchmarkSymbol,
  benchmarkLabel,
  benchmarkReturnPct,
  portfolioReturnPct,
  currency,
  periodDays,
  stale = false,
}: BenchmarkComparisonProps): React.ReactElement {
  const diff = portfolioReturnPct - benchmarkReturnPct;
  const outperforming = diff >= 0;

  return (
    <View style={styles.container}>
      <View style={styles.headerRow}>
        <Text style={styles.title}>
          vs {benchmarkLabel} ({benchmarkSymbol})
        </Text>
        {stale ? (
          <View style={styles.staleBadge}>
            <Text style={styles.staleText}>STALE</Text>
          </View>
        ) : null}
      </View>

      <Text style={styles.period}>
        {periodDays}d · {currency}
      </Text>

      <View style={styles.row}>
        <Text style={styles.label}>Portfolio</Text>
        <Text
          style={[
            styles.value,
            portfolioReturnPct >= 0 ? styles.gain : styles.loss,
          ]}
        >
          {arrow(portfolioReturnPct)} {formatPct(portfolioReturnPct)}
        </Text>
      </View>

      <View style={styles.row}>
        <Text style={styles.label}>{benchmarkLabel}</Text>
        <Text
          style={[
            styles.value,
            benchmarkReturnPct >= 0 ? styles.gain : styles.loss,
          ]}
        >
          {arrow(benchmarkReturnPct)} {formatPct(benchmarkReturnPct)}
        </Text>
      </View>

      <View style={[styles.row, styles.diffRow]}>
        <Text style={styles.label}>
          {outperforming ? 'Outperforming' : 'Underperforming'}
        </Text>
        <Text style={[styles.value, outperforming ? styles.gain : styles.loss]}>
          {formatPct(diff)}
        </Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    padding: 12,
    borderRadius: 8,
    backgroundColor: '#f6f8fa',
    marginVertical: 6,
  },
  headerRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  title: { fontSize: 15, fontWeight: '600', color: '#1f2328' },
  period: { fontSize: 12, color: '#656d76', marginTop: 2, marginBottom: 8 },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingVertical: 4,
  },
  diffRow: {
    marginTop: 6,
    paddingTop: 6,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: '#d0d7de',
  },
  label: { fontSize: 14, color: '#1f2328' },
  value: { fontSize: 14, fontVariant: ['tabular-nums'] },
  gain: { color: '#1a7f37' },
  loss: { color: '#cf222e' },
  staleBadge: {
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 4,
    backgroundColor: '#fff8c5',
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: '#d4a72c',
  },
  staleText: { fontSize: 10, fontWeight: '700', color: '#7d4e00' },
});
