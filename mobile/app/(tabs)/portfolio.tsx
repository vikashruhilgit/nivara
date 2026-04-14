import {
  ActivityIndicator,
  FlatList,
  RefreshControl,
  StyleSheet,
  Text,
  View,
} from 'react-native';

import { Position, usePortfolioSummary, usePositions } from '../../src/hooks/usePortfolio';

function formatCurrency(value: number, currency = 'USD'): string {
  try {
    return new Intl.NumberFormat(undefined, {
      style: 'currency',
      currency,
      maximumFractionDigits: 2,
    }).format(value);
  } catch {
    return `${currency} ${value.toFixed(2)}`;
  }
}

function PositionRow({ item }: { item: Position }): React.ReactElement {
  const gain = item.unrealized_pl >= 0;
  return (
    <View style={styles.row}>
      <View style={{ flex: 1 }}>
        <Text style={styles.symbol}>{item.symbol}</Text>
        <Text style={styles.sub}>
          {item.quantity} @ {formatCurrency(item.avg_cost, item.currency)}
        </Text>
      </View>
      <View style={{ alignItems: 'flex-end' }}>
        <Text style={styles.value}>{formatCurrency(item.market_value, item.currency)}</Text>
        <Text style={[styles.sub, gain ? styles.gain : styles.loss]}>
          {gain ? '+' : ''}
          {formatCurrency(item.unrealized_pl, item.currency)} ({item.unrealized_pl_pct.toFixed(2)}%)
        </Text>
      </View>
    </View>
  );
}

export default function PortfolioScreen(): React.ReactElement {
  const summary = usePortfolioSummary();
  const positions = usePositions();

  const refreshing = summary.isRefetching || positions.isRefetching;
  const onRefresh = (): void => {
    void summary.refetch();
    void positions.refetch();
  };

  const loading = summary.isPending || positions.isPending;

  if (loading) {
    return (
      <View style={styles.centered}>
        <ActivityIndicator size="large" />
      </View>
    );
  }

  const header = (
    <View style={styles.header}>
      {summary.data ? (
        <>
          <Text style={styles.totalLabel}>Total value</Text>
          <Text style={styles.totalValue}>
            {formatCurrency(summary.data.total_value, summary.data.currency)}
          </Text>
          <Text
            style={[
              styles.change,
              summary.data.day_change >= 0 ? styles.gain : styles.loss,
            ]}
          >
            {summary.data.day_change >= 0 ? '+' : ''}
            {formatCurrency(summary.data.day_change, summary.data.currency)} (
            {summary.data.day_change_pct.toFixed(2)}% today)
          </Text>
        </>
      ) : (
        <Text style={styles.sub}>Summary unavailable</Text>
      )}
    </View>
  );

  const empty = (
    <View style={styles.centered}>
      {positions.error ? (
        <Text style={styles.sub}>Positions unavailable. Pull down to retry.</Text>
      ) : (
        <Text style={styles.sub}>No positions yet. Connect a broker in Settings.</Text>
      )}
    </View>
  );

  return (
    <FlatList
      data={positions.data ?? []}
      keyExtractor={(p) => p.instrument_id}
      renderItem={PositionRow}
      ListHeaderComponent={header}
      ListEmptyComponent={empty}
      ItemSeparatorComponent={() => <View style={styles.sep} />}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} />}
      contentContainerStyle={styles.list}
    />
  );
}

const styles = StyleSheet.create({
  list: { padding: 16, gap: 8 },
  centered: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 32 },
  header: { marginBottom: 16 },
  totalLabel: { color: '#57606a', fontSize: 14 },
  totalValue: { fontSize: 32, fontWeight: '700', marginTop: 4 },
  change: { fontSize: 14, marginTop: 4 },
  row: { flexDirection: 'row', alignItems: 'center', paddingVertical: 12 },
  symbol: { fontSize: 16, fontWeight: '600' },
  value: { fontSize: 16, fontWeight: '600' },
  sub: { color: '#57606a', fontSize: 13, marginTop: 2 },
  gain: { color: '#1a7f37' },
  loss: { color: '#cf222e' },
  sep: { height: StyleSheet.hairlineWidth, backgroundColor: '#d0d7de' },
});
