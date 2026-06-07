/**
 * BenchmarkComparison — displays a single benchmark alongside the user's
 * portfolio return for the same period.
 *
 * Purely presentational. Parent supplies the numbers (fetched via
 * `useBenchmark` + portfolio data). Arrows indicate direction; a stale badge
 * appears when the benchmark data provider flagged the series as stale.
 */

import React, { useMemo } from 'react';
import { StyleSheet, View } from 'react-native';

import type { Theme } from '../theme';
import { useTheme } from '../theme';
import { Badge, Text } from '../ui';

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
  const theme = useTheme();
  const styles = useMemo(() => makeStyles(theme), [theme]);
  const diff = portfolioReturnPct - benchmarkReturnPct;
  const outperforming = diff >= 0;

  return (
    <View style={styles.container}>
      <View style={styles.headerRow}>
        <Text variant="label" weight="600">
          vs {benchmarkLabel} ({benchmarkSymbol})
        </Text>
        {stale ? <Badge label="STALE" tone="warning" /> : null}
      </View>

      <Text variant="caption" color="secondary" style={styles.period}>
        {periodDays}d · {currency}
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
          {arrow(portfolioReturnPct)} {formatPct(portfolioReturnPct)}
        </Text>
      </View>

      <View style={styles.row}>
        <Text variant="body" color="primary">
          {benchmarkLabel}
        </Text>
        <Text
          variant="body"
          weight="600"
          color={benchmarkReturnPct >= 0 ? 'positive' : 'negative'}
          style={styles.value}
        >
          {arrow(benchmarkReturnPct)} {formatPct(benchmarkReturnPct)}
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
    headerRow: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
    },
    period: { marginTop: 2, marginBottom: theme.spacing(2) },
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
