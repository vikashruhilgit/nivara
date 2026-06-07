import { useBottomTabBarHeight } from '@react-navigation/bottom-tabs';
import { useMemo } from 'react';
import { ActivityIndicator, FlatList, RefreshControl, StyleSheet, View } from 'react-native';

import { Recommendation } from '../../src/components/HoldingRow';
import { makeRenderHoldingRow } from '../../src/components/HoldingsList';
import { PortfolioSummary } from '../../src/components/PortfolioSummary';
import { usePortfolioSummary, usePositions } from '../../src/hooks/usePortfolio';
import { useRecommendations } from '../../src/hooks/useRecommendations';
import { useTheme } from '../../src/theme';
import type { Theme } from '../../src/theme';
import { Screen, Text } from '../../src/ui';

export default function PortfolioScreen(): React.ReactElement {
  const theme = useTheme();
  const styles = useMemo(() => makeStyles(theme), [theme]);
  const tabBarHeight = useBottomTabBarHeight();
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
      <Screen>
        <View style={styles.centered}>
          <ActivityIndicator size="large" color={theme.colors.accent} />
        </View>
      </Screen>
    );
  }

  const empty = (
    <View style={styles.centered}>
      {positions.error ? (
        <Text variant="caption" color="secondary">
          Positions unavailable. Pull down to retry.
        </Text>
      ) : (
        <Text variant="caption" color="secondary">
          No positions yet. Connect a broker in Settings.
        </Text>
      )}
    </View>
  );

  return (
    <Screen>
      <FlatList
        style={styles.flatList}
        data={positions.data ?? []}
        keyExtractor={(p) => p.instrument_id}
        renderItem={renderItem}
        ListHeaderComponent={<PortfolioSummary summary={summary.data} />}
        ListEmptyComponent={empty}
        ItemSeparatorComponent={() => (
          <View style={[styles.sep, { backgroundColor: theme.colors.border }]} />
        )}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={onRefresh}
            tintColor={theme.colors.accent}
            colors={[theme.colors.accent]}
          />
        }
        contentContainerStyle={[styles.list, { paddingBottom: theme.spacing(4) + tabBarHeight }]}
      />
    </Screen>
  );
}

function makeStyles(theme: Theme) {
  return StyleSheet.create({
    flatList: { backgroundColor: 'transparent' },
    list: { padding: theme.spacing(4), gap: theme.spacing(2) },
    centered: {
      flex: 1,
      alignItems: 'center',
      justifyContent: 'center',
      padding: theme.spacing(8),
    },
    sep: { height: StyleSheet.hairlineWidth },
  });
}
