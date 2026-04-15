/**
 * BlendedBenchmark — allocation-weighted benchmark for mixed-market portfolios.
 *
 * Shows the blend formula summary (e.g. "60% IN (Nifty) + 40% US (S&P)") and
 * the resulting total return in the user's base currency, alongside the
 * portfolio return for the same period.
 *
 * Purely presentational; parent supplies numbers (fetched via
 * `useBlendedBenchmark`).
 */

import React from 'react';
import { StyleSheet, Text, View } from 'react-native';

export interface BlendedBenchmarkWeight {
  venue: string;
  pct: number; // 0..100 (display units)
}

export interface BlendedBenchmarkProps {
  blendedReturnPct: number;
  portfolioReturnPct: number;
  baseCurrency: string;
  periodDays: number;
  weights: BlendedBenchmarkWeight[];
}

// Venue -> human index label used in the formula summary.
const VENUE_LABEL: Record<string, string> = {
  XNSE: 'Nifty',
  XBOM: 'Sensex',
  XNAS: 'Nasdaq',
  XNYS: 'S&P',
  US: 'S&P',
  IN: 'Nifty',
};

function venueLabel(venue: string): string {
  return VENUE_LABEL[venue] ?? venue;
}

function formatPct(pct: number): string {
  const sign = pct >= 0 ? '+' : '';
  return `${sign}${pct.toFixed(2)}%`;
}

function buildFormula(weights: BlendedBenchmarkWeight[]): string {
  return weights
    .map((w) => `${w.pct.toFixed(0)}% ${w.venue} (${venueLabel(w.venue)})`)
    .join(' + ');
}

export function BlendedBenchmark({
  blendedReturnPct,
  portfolioReturnPct,
  baseCurrency,
  periodDays,
  weights,
}: BlendedBenchmarkProps): React.ReactElement {
  const diff = portfolioReturnPct - blendedReturnPct;
  const outperforming = diff >= 0;
  const formula = buildFormula(weights);

  return (
    <View style={styles.container}>
      <Text style={styles.title}>Blended Benchmark</Text>
      <Text style={styles.period}>
        {periodDays}d · base {baseCurrency}
      </Text>

      <Text style={styles.formula} numberOfLines={2}>
        {formula}
      </Text>

      <View style={styles.row}>
        <Text style={styles.label}>Portfolio</Text>
        <Text
          style={[
            styles.value,
            portfolioReturnPct >= 0 ? styles.gain : styles.loss,
          ]}
        >
          {formatPct(portfolioReturnPct)}
        </Text>
      </View>

      <View style={styles.row}>
        <Text style={styles.label}>Blended</Text>
        <Text
          style={[
            styles.value,
            blendedReturnPct >= 0 ? styles.gain : styles.loss,
          ]}
        >
          {formatPct(blendedReturnPct)}
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
  title: { fontSize: 15, fontWeight: '600', color: '#1f2328' },
  period: { fontSize: 12, color: '#656d76', marginTop: 2 },
  formula: {
    fontSize: 13,
    color: '#1f2328',
    marginTop: 8,
    marginBottom: 8,
    fontStyle: 'italic',
  },
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
});
