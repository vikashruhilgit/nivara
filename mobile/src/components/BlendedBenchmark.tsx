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

import React, { useMemo } from 'react';
import { StyleSheet, View } from 'react-native';

import type { Theme } from '../theme';
import { useTheme } from '../theme';
import { Text } from '../ui';

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
  const theme = useTheme();
  const styles = useMemo(() => makeStyles(theme), [theme]);
  const diff = portfolioReturnPct - blendedReturnPct;
  const outperforming = diff >= 0;
  const formula = buildFormula(weights);

  return (
    <View style={styles.container}>
      <Text variant="label" weight="600">
        Blended Benchmark
      </Text>
      <Text variant="caption" color="secondary" style={styles.period}>
        {periodDays}d · base {baseCurrency}
      </Text>

      <Text
        variant="caption"
        color="primary"
        numberOfLines={2}
        style={styles.formula}
      >
        {formula}
      </Text>

      <View style={styles.row}>
        <Text variant="body" color="primary">
          Portfolio
        </Text>
        <Text
          variant="body"
          weight="600"
          color={portfolioReturnPct >= 0 ? 'positive' : 'negative'}
          style={styles.value}
        >
          {formatPct(portfolioReturnPct)}
        </Text>
      </View>

      <View style={styles.row}>
        <Text variant="body" color="primary">
          Blended
        </Text>
        <Text
          variant="body"
          weight="600"
          color={blendedReturnPct >= 0 ? 'positive' : 'negative'}
          style={styles.value}
        >
          {formatPct(blendedReturnPct)}
        </Text>
      </View>

      <View style={[styles.row, styles.diffRow]}>
        <Text variant="body" color="primary">
          {outperforming ? 'Outperforming' : 'Underperforming'}
        </Text>
        <Text
          variant="body"
          weight="600"
          color={outperforming ? 'positive' : 'negative'}
          style={styles.value}
        >
          {formatPct(diff)}
        </Text>
      </View>
    </View>
  );
}

function makeStyles(theme: Theme) {
  return StyleSheet.create({
    container: {
      padding: theme.spacing(3),
      borderRadius: theme.radii.md,
      backgroundColor: theme.colors.surfaceAlt,
      borderWidth: StyleSheet.hairlineWidth,
      borderColor: theme.colors.border,
      marginVertical: theme.spacing(1.5),
    },
    period: { marginTop: 2 },
    formula: {
      marginTop: theme.spacing(2),
      marginBottom: theme.spacing(2),
      fontStyle: 'italic',
    },
    row: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      paddingVertical: theme.spacing(1),
    },
    diffRow: {
      marginTop: theme.spacing(1.5),
      paddingTop: theme.spacing(1.5),
      borderTopWidth: StyleSheet.hairlineWidth,
      borderTopColor: theme.colors.border,
    },
    value: { fontVariant: ['tabular-nums'] },
  });
}
