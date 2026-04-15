import { StyleSheet, Text, View } from 'react-native';

import { Recommendation, RecommendationAction } from '../hooks/useRecommendations';
import { FreshnessBadge } from './FreshnessBadge';
import { StaleDataMessage } from './StaleDataMessage';

function actionLabel(action: RecommendationAction): string {
  switch (action) {
    case 'strong_buy':
      return 'STRONG BUY';
    case 'buy':
      return 'BUY';
    case 'hold':
      return 'HOLD';
    case 'sell':
      return 'SELL';
    case 'strong_sell':
      return 'STRONG SELL';
  }
}

function actionColors(action: RecommendationAction): { bg: string; fg: string } {
  if (action === 'buy' || action === 'strong_buy') {
    return { bg: '#dafbe1', fg: '#1a7f37' };
  }
  if (action === 'sell' || action === 'strong_sell') {
    return { bg: '#ffebe9', fg: '#cf222e' };
  }
  return { bg: '#eaeef2', fg: '#57606a' };
}

function explainerLabel(explainer: string): string {
  const key = explainer.toLowerCase();
  if (key.includes('openai') || key.includes('gpt')) return 'OpenAI';
  if (key.includes('anthropic') || key.includes('claude')) return 'Anthropic';
  if (key.includes('heuristic') || key.includes('rule')) return 'Heuristic';
  return explainer.charAt(0).toUpperCase() + explainer.slice(1);
}

function timeAgo(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return '';
  const diffMs = Date.now() - then;
  const sec = Math.max(0, Math.floor(diffMs / 1000));
  if (sec < 60) return `${sec}s ago`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const day = Math.floor(hr / 24);
  if (day < 30) return `${day}d ago`;
  const mo = Math.floor(day / 30);
  if (mo < 12) return `${mo}mo ago`;
  const yr = Math.floor(day / 365);
  return `${yr}y ago`;
}

export interface InsightCardProps {
  rec: Recommendation;
  staleness?: 'fresh' | 'aging' | 'stale' | 'suppressed';
}

export function InsightCard({ rec, staleness }: InsightCardProps): React.ReactElement {
  const symbol = rec.symbol ?? rec.instrument_id ?? 'Unknown';
  const action = rec.action ?? null;
  const colors = action ? actionColors(action) : null;
  const effectiveStaleness = staleness ?? rec.staleness;

  if (effectiveStaleness === 'suppressed') {
    return (
      <View style={styles.card}>
        <View style={styles.headerRow}>
          <Text style={styles.symbol}>{symbol}</Text>
          <FreshnessBadge level="suppressed" />
        </View>
        <StaleDataMessage level="suppressed" />
      </View>
    );
  }

  return (
    <View style={styles.card}>
      <View style={styles.headerRow}>
        <Text style={styles.symbol}>{symbol}</Text>
        <View style={styles.headerRight}>
          {effectiveStaleness && effectiveStaleness !== 'fresh' ? (
            <FreshnessBadge level={effectiveStaleness} />
          ) : null}
          {action && colors ? (
            <View style={[styles.badge, { backgroundColor: colors.bg }]}>
              <Text style={[styles.badgeText, { color: colors.fg }]}>{actionLabel(action)}</Text>
            </View>
          ) : null}
        </View>
      </View>

      <View style={styles.metaRow}>
        {typeof rec.confidence === 'number' ? (
          <Text style={styles.meta}>Confidence {rec.confidence.toFixed(0)}%</Text>
        ) : null}
        {rec.computed_at ? <Text style={styles.metaDot}>{timeAgo(rec.computed_at)}</Text> : null}
      </View>

      {rec.rationale ? (
        <Text style={styles.rationale} numberOfLines={3}>
          {rec.rationale}
        </Text>
      ) : null}

      <View style={styles.footerRow}>
        {rec.explainer_used ? (
          <View style={styles.providerBadge}>
            <Text style={styles.providerText}>{explainerLabel(rec.explainer_used)}</Text>
          </View>
        ) : null}
        {rec.ai_blended ? (
          <View style={styles.providerBadge}>
            <Text style={styles.providerText}>AI blended</Text>
          </View>
        ) : null}
        {rec.status === 'stale' ? (
          <View style={[styles.providerBadge, styles.staleBadge]}>
            <Text style={[styles.providerText, styles.staleText]}>stale</Text>
          </View>
        ) : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: '#fff',
    borderRadius: 12,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: '#d0d7de',
    padding: 16,
    marginBottom: 12,
    gap: 8,
  },
  headerRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  headerRight: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  symbol: { fontSize: 18, fontWeight: '700' },
  badge: {
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 999,
  },
  badgeText: { fontSize: 11, fontWeight: '700', letterSpacing: 0.3 },
  metaRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  meta: { fontSize: 13, color: '#57606a', fontWeight: '600' },
  metaDot: { fontSize: 13, color: '#57606a' },
  rationale: { fontSize: 14, color: '#1f2328', lineHeight: 20 },
  footerRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginTop: 2 },
  providerBadge: {
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 999,
    backgroundColor: '#f6f8fa',
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: '#d0d7de',
  },
  providerText: { fontSize: 11, color: '#57606a', fontWeight: '600' },
  staleBadge: { backgroundColor: '#fff8c5', borderColor: '#d4a72c' },
  staleText: { color: '#9a6700' },
});
