import React, { useMemo } from 'react';
import { StyleSheet, View } from 'react-native';

import type { PortfolioSummary as PortfolioSummaryData } from '../hooks/usePortfolio';
import { formatCurrency } from '../lib/format';
import type { Theme } from '../theme';
import { useTheme } from '../theme';
import { Surface, Text } from '../ui';
import { PnLDisplay } from './PnLDisplay';

export interface PortfolioSummaryProps {
  summary: PortfolioSummaryData | undefined;
}

export function PortfolioSummary({
  summary,
}: PortfolioSummaryProps): React.ReactElement {
  const theme = useTheme();
  const styles = useMemo(() => makeStyles(theme), [theme]);

  if (!summary) {
    return (
      <Surface context="static" elevation="md" style={styles.hero}>
        <View style={styles.heroInner}>
          <Text variant="caption" color="tertiary">
            Summary unavailable
          </Text>
        </View>
      </Surface>
    );
  }

  return (
    <Surface context="static" elevation="md" style={styles.hero}>
      <View style={styles.heroInner}>
        <Text variant="label" color="secondary" style={styles.uppercase}>
          Total value
        </Text>
        <Text variant="h1" weight="700" style={styles.totalValue}>
          {formatCurrency(summary.total_value, summary.currency)}
        </Text>
        <View style={styles.metaRow}>
          <PnLDisplay
            amount={summary.day_change}
            pct={summary.day_change_pct}
            currency={summary.currency}
          />
          <Text variant="caption" color="tertiary" style={styles.currencyPill}>
            {summary.currency}
          </Text>
        </View>
      </View>
    </Surface>
  );
}

function makeStyles(theme: Theme) {
  return StyleSheet.create({
    hero: { marginBottom: theme.spacing(4) },
    heroInner: { padding: theme.spacing(5) },
    uppercase: { letterSpacing: 0.5, textTransform: 'uppercase' },
    totalValue: {
      marginTop: theme.spacing(2),
      fontVariant: ['tabular-nums'],
    },
    metaRow: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      marginTop: theme.spacing(1),
    },
    currencyPill: {
      backgroundColor: theme.colors.surfaceAlt,
      borderRadius: theme.radii.pill,
      paddingHorizontal: theme.spacing(2),
      paddingVertical: theme.spacing(1),
      overflow: 'hidden',
      letterSpacing: 0.5,
    },
  });
}
