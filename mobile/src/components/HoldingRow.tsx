import React from 'react';
import { StyleSheet, Text, View } from 'react-native';

import type { Position } from '../hooks/usePortfolio';
import { formatCurrency } from '../lib/format';
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
    <View style={styles.row}>
      <View style={{ flex: 1 }}>
        <Text style={styles.symbol}>{item.symbol}</Text>
        <Text style={styles.sub}>
          {item.quantity} @ {formatCurrency(item.avg_cost, item.currency)}
        </Text>
      </View>
      <View style={{ alignItems: 'flex-end' }}>
        <Text style={styles.value}>
          {formatCurrency(item.market_value, item.currency)}
        </Text>
        <Text style={[styles.sub, gain ? styles.gain : styles.loss]}>
          {nativePL}
        </Text>
        {basePL !== null ? <Text style={styles.muted}>{basePL}</Text> : null}
        {crossCurrency && (fxAttribution ?? item.fx_attribution) ? (
          <FxImpactNote
            attribution={(fxAttribution ?? item.fx_attribution) as FxAttribution}
          />
        ) : null}
        {recommendation ? (
          <AIRatingBadge
            action={recommendation.action}
            confidence={recommendation.confidence}
          />
        ) : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center', paddingVertical: 12 },
  symbol: { fontSize: 16, fontWeight: '600' },
  value: { fontSize: 16, fontWeight: '600' },
  sub: { color: '#57606a', fontSize: 13, marginTop: 2 },
  muted: { color: '#8c959f', fontSize: 12, marginTop: 1, fontStyle: 'italic' },
  gain: { color: '#1a7f37' },
  loss: { color: '#cf222e' },
});
