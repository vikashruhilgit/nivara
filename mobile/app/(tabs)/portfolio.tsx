import { useMemo } from 'react';
import {
  ActivityIndicator,
  FlatList,
  RefreshControl,
  StyleSheet,
  Text,
  View,
} from 'react-native';

import { Recommendation } from '../../src/components/HoldingRow';
import { makeRenderHoldingRow } from '../../src/components/HoldingsList';
import { PortfolioSummary } from '../../src/components/PortfolioSummary';
import { usePortfolioSummary, usePositions } from '../../src/hooks/usePortfolio';
import { useRecommendations } from '../../src/hooks/useRecommendations';

export default function PortfolioScreen(): React.ReactElement {
  const summary = usePortfolioSummary();
  const positions = usePositions();
  const recommendations = useRecommendations();
  const baseCurrency = summary.data?.currency ?? 'USD';

  const recommendationsByInstrument = useMemo<Record<string, Recommendation>>(() => {
    const out: Record<string, Recommendation> = {};
    for (const r of recommendations.data ?? []) {
      if (!r.instrument_id) continue;
      out[r.instrument_id] = {
        instrument_id: r.instrument_id,
        action: r.action ?? null,
        confidence: r.confidence ?? null,
      };
    }
    return out;
  }, [recommendations.data]);

  const renderItem = useMemo(
    () => makeRenderHoldingRow(baseCurrency, recommendationsByInstrument),
    [baseCurrency, recommendationsByInstrument],
  );

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
      renderItem={renderItem}
      ListHeaderComponent={<PortfolioSummary summary={summary.data} />}
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
  sub: { color: '#57606a', fontSize: 13, marginTop: 2 },
  sep: { height: StyleSheet.hairlineWidth, backgroundColor: '#d0d7de' },
});
