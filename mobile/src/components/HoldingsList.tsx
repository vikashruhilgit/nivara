import React from 'react';
import { ListRenderItem, StyleSheet, View } from 'react-native';

import type { Position } from '../hooks/usePortfolio';
import { HoldingRow, Recommendation } from './HoldingRow';

export interface HoldingsListProps {
  positions: Position[];
  baseCurrency: string;
  recommendationsByInstrument?: Record<string, Recommendation>;
}

/**
 * Composition component: renders all holdings as a vertical list of
 * HoldingRow components separated by a hairline. Intended for use when the
 * parent is NOT already a FlatList (e.g., inside a ScrollView).
 */
export function HoldingsList({
  positions,
  baseCurrency,
  recommendationsByInstrument,
}: HoldingsListProps): React.ReactElement {
  return (
    <View>
      {positions.map((p, idx) => (
        <View key={p.instrument_id}>
          {idx > 0 ? <View style={styles.sep} /> : null}
          <HoldingRow
            item={p}
            baseCurrency={baseCurrency}
            recommendation={recommendationsByInstrument?.[p.instrument_id] ?? null}
          />
        </View>
      ))}
    </View>
  );
}

/**
 * FlatList-friendly renderItem helper. Bind `baseCurrency` + optional
 * recommendations lookup via closure, then pass the returned function to
 * `<FlatList renderItem={...} />`.
 */
export function makeRenderHoldingRow(
  baseCurrency: string,
  recommendationsByInstrument?: Record<string, Recommendation>,
): ListRenderItem<Position> {
  const render: ListRenderItem<Position> = ({ item }) => (
    <HoldingRow
      item={item}
      baseCurrency={baseCurrency}
      recommendation={recommendationsByInstrument?.[item.instrument_id] ?? null}
    />
  );
  return render;
}

const styles = StyleSheet.create({
  sep: { height: StyleSheet.hairlineWidth, backgroundColor: '#d0d7de' },
});
