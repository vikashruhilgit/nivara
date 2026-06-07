import React, { useMemo } from 'react';
import { StyleSheet, View } from 'react-native';

import type { Position } from '../hooks/usePortfolio';
import { formatCurrency } from '../lib/format';
import type { Theme } from '../theme';
import { useTheme } from '../theme';
import { Card, Text } from '../ui';
import { AIRatingBadge, RecommendationAction } from './AIRatingBadge';
import { FxImpactNote, FxAttribution } from './FxImpactNote';

export interface Recommendation {
  instrument_id: string;
  action: RecommendationAction | null;
  confidence: number | null;
}

export interface HoldingRowProps {
  item: Position;
  baseCurrency: string;
  recommendation?: Recommendation | null;
  /**
   * Optional FX attribution. When provided and the holding is cross-currency,
   * a muted note is rendered beneath the base-currency placeholder row.
   * Falls back to `item.fx_attribution` if not explicitly passed.
   */
  fxAttribution?: FxAttribution | null;
}

export function HoldingRow({
  item,
  baseCurrency,
  recommendation,
  fxAttribution,
}: HoldingRowProps): React.ReactElement {
  const theme = useTheme();
  const styles = useMemo(() => makeStyles(theme), [theme]);
  const gain = item.unrealized_pl >= 0;
  const crossCurrency = item.currency !== baseCurrency;

  // FX conversion not yet available on mobile client. When cross-currency,
  // we display the native P&L and also a muted base-currency label with the
  // same amount (placeholder for future FX-converted value). This keeps the
  // UI structure in place for when FX rates are wired in.
  // TODO: replace the repeated native amount with an FX-converted amount
  //       once an FX rate hook is available.
  const nativePL = `${gain ? '+' : ''}${formatCurrency(item.unrealized_pl, item.currency)} (${item.unrealized_pl_pct.toFixed(2)}%)`;
  const basePL = crossCurrency
    ? `~${formatCurrency(item.unrealized_pl, baseCurrency)} (${baseCurrency})`
    : null;

  return (
    <Card context="list" style={styles.card}>
      <View style={styles.row}>
        <View style={styles.left}>
          <Text variant="title" weight="600">
            {item.symbol}
          </Text>
          <Text variant="caption" color="secondary" style={styles.subSpacing}>
            {item.quantity} @ {formatCurrency(item.avg_cost, item.currency)}
          </Text>
        </View>
        <View style={styles.right}>
          <Text variant="title" weight="600" style={styles.tnum}>
            {formatCurrency(item.market_value, item.currency)}
          </Text>
          <Text
            variant="caption"
            weight="600"
            color={gain ? 'positive' : 'negative'}
            style={[styles.subSpacing, styles.tnum]}
          >
            {nativePL}
          </Text>
          {basePL !== null ? (
            <Text
              variant="caption"
              color="tertiary"
              style={[styles.mutedSpacing, styles.italic]}
            >
              {basePL}
            </Text>
          ) : null}
          {crossCurrency && (fxAttribution ?? item.fx_attribution) ? (
            <FxImpactNote
              attribution={(fxAttribution ?? item.fx_attribution) as FxAttribution}
            />
          ) : null}
          {recommendation ? (
            <View style={styles.badgeSpacing}>
              <AIRatingBadge
                action={recommendation.action}
                confidence={recommendation.confidence}
              />
            </View>
          ) : null}
        </View>
      </View>
    </Card>
  );
}

function makeStyles(theme: Theme) {
  return StyleSheet.create({
    card: { marginVertical: theme.spacing(1) },
    row: { flexDirection: 'row', alignItems: 'center' },
    left: { flex: 1 },
    right: { alignItems: 'flex-end' },
    subSpacing: { marginTop: theme.spacing(0.5) },
    mutedSpacing: { marginTop: 1 },
    badgeSpacing: { marginTop: theme.spacing(1) },
    italic: { fontStyle: 'italic' },
    tnum: { fontVariant: ['tabular-nums'] },
  });
}
