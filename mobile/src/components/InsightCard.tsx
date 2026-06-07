import { useMemo } from 'react';
import { StyleSheet, View } from 'react-native';

import { Recommendation, RecommendationAction } from '../hooks/useRecommendations';
import { useTheme } from '../theme';
import type { Theme } from '../theme';
import { Surface, Text } from '../ui';
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

/**
 * Semantic mapping for a recommendation action, resolved against the theme:
 *   buy / strong_buy   → positive (positiveBg / positive)
 *   sell / strong_sell → negative (negativeBg / negative)
 *   hold / neutral     → neutral  (neutralBg / neutral)
 */
function actionColors(theme: Theme, action: RecommendationAction): { bg: string; fg: string } {
  if (action === 'buy' || action === 'strong_buy') {
    return { bg: theme.colors.positiveBg, fg: theme.colors.positive };
  }
  if (action === 'sell' || action === 'strong_sell') {
    return { bg: theme.colors.negativeBg, fg: theme.colors.negative };
  }
  return { bg: theme.colors.neutralBg, fg: theme.colors.neutral };
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

function makeStyles(theme: Theme) {
  return StyleSheet.create({
    card: {
      padding: theme.spacing(4),
      gap: theme.spacing(2),
    },
    headerRow: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
    },
    headerRight: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: theme.spacing(1.5),
    },
    badge: {
      paddingHorizontal: theme.spacing(2.5),
      paddingVertical: theme.spacing(1),
      borderRadius: theme.radii.pill,
    },
    metaRow: { flexDirection: 'row', alignItems: 'center', gap: theme.spacing(2) },
    rationale: { marginTop: theme.spacing(0.5) },
    footerRow: {
      flexDirection: 'row',
      flexWrap: 'wrap',
      gap: theme.spacing(1.5),
      marginTop: theme.spacing(0.5),
    },
    providerBadge: {
      paddingHorizontal: theme.spacing(2),
      paddingVertical: theme.spacing(0.75),
      borderRadius: theme.radii.pill,
      backgroundColor: theme.colors.surfaceAlt,
      borderWidth: StyleSheet.hairlineWidth,
      borderColor: theme.colors.border,
    },
    staleBadge: {
      backgroundColor: theme.colors.warningBg,
      borderColor: theme.colors.warningBorder,
    },
  });
}

export interface InsightCardProps {
  rec: Recommendation;
  staleness?: 'fresh' | 'aging' | 'stale' | 'suppressed';
}

export function InsightCard({ rec, staleness }: InsightCardProps): React.ReactElement {
  const theme = useTheme();
  const styles = useMemo(() => makeStyles(theme), [theme]);

  const symbol = rec.symbol ?? rec.instrument_id ?? 'Unknown';
  const action = rec.action ?? null;
  const colors = action ? actionColors(theme, action) : null;
  const effectiveStaleness = staleness ?? rec.staleness;

  if (effectiveStaleness === 'suppressed') {
    return (
      <Surface context="list" style={styles.card}>
        <View style={styles.headerRow}>
          <Text variant="title">{symbol}</Text>
          <FreshnessBadge level="suppressed" />
        </View>
        <StaleDataMessage level="suppressed" />
      </Surface>
    );
  }

  return (
    <Surface context="list" style={styles.card}>
      <View style={styles.headerRow}>
        <Text variant="title">{symbol}</Text>
        <View style={styles.headerRight}>
          {effectiveStaleness && effectiveStaleness !== 'fresh' ? (
            <FreshnessBadge level={effectiveStaleness} />
          ) : null}
          {action && colors ? (
            <View style={[styles.badge, { backgroundColor: colors.bg }]}>
              <Text variant="caption" weight="700" style={{ color: colors.fg, letterSpacing: 0.3 }}>
                {actionLabel(action)}
              </Text>
            </View>
          ) : null}
        </View>
      </View>

      <View style={styles.metaRow}>
        {typeof rec.confidence === 'number' ? (
          <Text variant="label" color="secondary">
            Confidence {rec.confidence.toFixed(0)}%
          </Text>
        ) : null}
        {rec.computed_at ? (
          <Text variant="caption" color="tertiary">
            {timeAgo(rec.computed_at)}
          </Text>
        ) : null}
      </View>

      {rec.rationale ? (
        <Text variant="body" color="primary" numberOfLines={3} style={styles.rationale}>
          {rec.rationale}
        </Text>
      ) : null}

      <View style={styles.footerRow}>
        {rec.explainer_used ? (
          <View style={styles.providerBadge}>
            <Text variant="caption" color="secondary" weight="600">
              {explainerLabel(rec.explainer_used)}
            </Text>
          </View>
        ) : null}
        {rec.ai_blended ? (
          <View style={styles.providerBadge}>
            <Text variant="caption" color="secondary" weight="600">
              AI blended
            </Text>
          </View>
        ) : null}
        {rec.status === 'stale' ? (
          <View style={[styles.providerBadge, styles.staleBadge]}>
            <Text variant="caption" color="warning" weight="600">
              stale
            </Text>
          </View>
        ) : null}
      </View>
    </Surface>
  );
}
