import { useMemo } from 'react';
import {
  ActivityIndicator,
  FlatList,
  RefreshControl,
  StyleSheet,
  Text,
  View,
} from 'react-native';

import { Recommendation, useRecommendations } from '../hooks/useRecommendations';
import { InsightCard } from './InsightCard';

function keyFor(rec: Recommendation, index: number): string {
  const base = rec.instrument_id ?? rec.symbol ?? 'rec';
  return `${base}-${rec.computed_at ?? index}-${index}`;
}

export function InsightFeed(): React.ReactElement {
  const query = useRecommendations();

  const sorted = useMemo<Recommendation[]>(() => {
    const data = query.data ?? [];
    return [...data].sort((a, b) => {
      const ta = a.computed_at ? new Date(a.computed_at).getTime() : 0;
      const tb = b.computed_at ? new Date(b.computed_at).getTime() : 0;
      return tb - ta;
    });
  }, [query.data]);

  if (query.isPending) {
    return (
      <View style={styles.centered}>
        <ActivityIndicator size="large" />
      </View>
    );
  }

  const empty = (
    <View style={styles.centered}>
      {query.error ? (
        <Text style={styles.sub}>Recommendations unavailable. Pull down to retry.</Text>
      ) : (
        <Text style={styles.sub}>No recommendations yet.</Text>
      )}
    </View>
  );

  return (
    <FlatList
      data={sorted}
      keyExtractor={keyFor}
      renderItem={({ item }) => <InsightCard rec={item} />}
      ListEmptyComponent={empty}
      refreshControl={
        <RefreshControl
          refreshing={query.isRefetching}
          onRefresh={() => {
            void query.refetch();
          }}
        />
      }
      contentContainerStyle={styles.list}
    />
  );
}

const styles = StyleSheet.create({
  list: { padding: 16, flexGrow: 1 },
  centered: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 32 },
  sub: { color: '#57606a', fontSize: 14, textAlign: 'center' },
});
