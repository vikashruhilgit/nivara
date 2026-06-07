import React from 'react';
import { ListRenderItem, View } from 'react-native';

import type { Position } from '../hooks/usePortfolio';
import { useTheme } from '../theme';
import { HoldingRow, Recommendation } from './HoldingRow';

export interface HoldingsListProps {
  positions: Position[];
  baseCurrency: string;
  recommendationsByInstrument?: Record<string, Recommendation>;
}

/**
 * Composition component: renders all holdings as a vertical list of
 * HoldingRow glass cards. Intended for use when the parent is NOT already a
 * FlatList (e.g., inside a ScrollView).
 */
export function HoldingsList({
  positions,
  baseCurrency,
  recommendationsByInstrument,
}: HoldingsListProps): React.ReactElement {
  const theme = useTheme();
  return (
    <View style={{ gap: theme.spacing(2) }}>
      {positions.map((p) => (
        <HoldingRow
          key={p.instrument_id}
          item={p}
          baseCurrency={baseCurrency}
          recommendation={recommendationsByInstrument?.[p.instrument_id] ?? null}
        />
      ))}
    </View>
  );
}

/**
 * FlatList-friendly renderItem helper. Bind `baseCurrency` + optional
 * recommendations lookup via closure, then pass the returned function to
 * `<FlatList renderItem={...} />`.
 *
 * Each HoldingRow is now a self-contained glass card (Card context='list'),
 * so no inter-row separator View is needed — the FlatList contentContainer
 * provides the row gap.
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
