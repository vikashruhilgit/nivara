import { useBottomTabBarHeight } from '@react-navigation/bottom-tabs';
import { useMemo } from 'react';
import { ActivityIndicator, FlatList, RefreshControl, View } from 'react-native';

import { Recommendation, useRecommendations } from '../hooks/useRecommendations';
import { useTheme } from '../theme';
import { Text } from '../ui';
import { InsightCard } from './InsightCard';

function keyFor(rec: Recommendation, index: number): string {
  const base = rec.instrument_id ?? rec.symbol ?? 'rec';
  return `${base}-${rec.computed_at ?? index}-${index}`;
}

export function InsightFeed(): React.ReactElement {
  const theme = useTheme();
  const tabBarHeight = useBottomTabBarHeight();
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
      <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', padding: theme.spacing(8) }}>
        <ActivityIndicator size="large" color={theme.colors.accent} />
      </View>
    );
  }

  const empty = (
    <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', padding: theme.spacing(8) }}>
      <Text variant="body" color="secondary" style={{ textAlign: 'center' }}>
        {query.error
          ? 'Recommendations unavailable. Pull down to retry.'
          : 'No recommendations yet.'}
      </Text>
    </View>
  );

  return (
    <FlatList
      data={sorted}
      keyExtractor={keyFor}
      renderItem={({ item }) => <InsightCard rec={item} />}
      ListEmptyComponent={empty}
      ItemSeparatorComponent={() => (
        <View style={{ height: theme.spacing(3) }} />
      )}
      refreshControl={
        <RefreshControl
          refreshing={query.isRefetching}
          onRefresh={() => {
            void query.refetch();
          }}
          tintColor={theme.colors.accent}
          colors={[theme.colors.accent]}
        />
      }
      contentContainerStyle={{
        padding: theme.spacing(4),
        paddingBottom: theme.spacing(4) + tabBarHeight,
        flexGrow: 1,
      }}
    />
  );
}
