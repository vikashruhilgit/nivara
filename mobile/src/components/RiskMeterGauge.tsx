/**
 * RiskMeterGauge - half-circle (180 degree) gauge rendering a 0-100 score.
 *
 * Implemented with pure React Native Views (no SVG dependency). The needle
 * is a thin rectangle rotated from -90 (score=0) through 0 (score=50) to
 * +90 (score=100). The dial is a half-circle split into three colored
 * zones via absolutely positioned View slices behind an inner disc.
 *
 * Color zones map to theme status tokens: 0-30 positive (low risk),
 * 31-60 warning (medium), 61-100 negative (high).
 */

import React, { useMemo } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import type { Theme } from '../theme';
import { useTheme } from '../theme';

const GAUGE_SIZE = 220;
const GAUGE_RADIUS = GAUGE_SIZE / 2;
const INNER_RADIUS = GAUGE_RADIUS - 24;

/**
 * Resolve the status color for a risk score from the theme tokens.
 * 0-30 → positive (low), 31-60 → warning (medium), 61-100 → negative (high).
 */
export function zoneColor(theme: Theme, score: number): string {
  if (score <= 30) return theme.colors.positive;
  if (score <= 60) return theme.colors.warning;
  return theme.colors.negative;
}

export interface RiskMeterGaugeProps {
  score: number;
  color: string;
  onPress?: () => void;
}

function Slice({
  startDeg,
  endDeg,
  color,
}: {
  startDeg: number;
  endDeg: number;
  color: string;
}): React.ReactElement {
  const sweep = endDeg - startDeg;
  const mid = (startDeg + endDeg) / 2;
  return (
    <View
      style={[
        styles.slice,
        {
          backgroundColor: color,
          transform: [{ rotate: `${mid}deg` }],
          width: GAUGE_RADIUS * 2 * Math.sin((sweep * Math.PI) / 360) * 1.05,
        },
      ]}
    />
  );
}

export function RiskMeterGauge({
  score,
  color,
  onPress,
}: RiskMeterGaugeProps): React.ReactElement {
  const theme = useTheme();
  const styles2 = useMemo(() => makeStyles(theme), [theme]);
  const clamped = Math.max(0, Math.min(100, score));
  const needleDeg = -90 + (clamped / 100) * 180;
  const resolvedColor = color || zoneColor(theme, clamped);

  const lowColor = theme.colors.positive;
  const medColor = theme.colors.warning;
  const highColor = theme.colors.negative;
  const discColor = theme.colors.surface;

  const body = (
    <View style={styles2.card}>
      <Text style={styles2.title}>Risk Meter</Text>
      <View style={styles.gauge}>
        <Slice startDeg={-90} endDeg={-36} color={lowColor} />
        <Slice startDeg={-36} endDeg={18} color={medColor} />
        <Slice startDeg={18} endDeg={90} color={highColor} />
        <View style={[styles.innerDisc, { backgroundColor: discColor }]} />
        <View style={[styles.bottomMask, { backgroundColor: discColor }]} />
        <View
          style={[
            styles.needle,
            { backgroundColor: theme.colors.textPrimary },
            { transform: [{ translateX: -2 }, { rotate: `${needleDeg}deg` }] },
          ]}
        />
        <View style={styles.centerLabel} pointerEvents="none">
          <Text style={[styles.score, { color: resolvedColor }]}>
            {Math.round(clamped)}
          </Text>
          <Text style={styles2.scoreSub}>/ 100</Text>
        </View>
      </View>
      <View style={styles.legend}>
        <LegendDot color={lowColor} label="Low" />
        <LegendDot color={medColor} label="Medium" />
        <LegendDot color={highColor} label="High" />
      </View>
      {onPress ? <Text style={styles2.hint}>Tap for breakdown</Text> : null}
    </View>
  );

  if (onPress) {
    return (
      <Pressable
        onPress={onPress}
        accessibilityRole="button"
        accessibilityLabel={`Risk meter score ${Math.round(clamped)} of 100. Tap for breakdown.`}
      >
        {body}
      </Pressable>
    );
  }
  return body;
}

function LegendDot({
  color,
  label,
}: {
  color: string;
  label: string;
}): React.ReactElement {
  const theme = useTheme();
  return (
    <View style={styles.legendItem}>
      <View style={[styles.legendDot, { backgroundColor: color }]} />
      <Text style={[styles.legendText, { color: theme.colors.textSecondary }]}>
        {label}
      </Text>
    </View>
  );
}

function makeStyles(theme: Theme) {
  return StyleSheet.create({
    card: {
      backgroundColor: theme.colors.surface,
      borderRadius: theme.radii.lg,
      padding: theme.spacing(4),
      borderWidth: StyleSheet.hairlineWidth,
      borderColor: theme.colors.border,
      alignItems: 'center',
    },
    title: {
      fontSize: theme.typography.label.fontSize,
      color: theme.colors.textSecondary,
      alignSelf: 'flex-start',
      marginBottom: theme.spacing(2),
    },
    scoreSub: {
      fontSize: theme.typography.caption.fontSize,
      color: theme.colors.textSecondary,
      marginTop: 2,
    },
    hint: {
      marginTop: theme.spacing(2),
      fontSize: theme.typography.caption.fontSize,
      color: theme.colors.textSecondary,
    },
  });
}

const styles = StyleSheet.create({
  gauge: {
    width: GAUGE_SIZE,
    height: GAUGE_RADIUS + 24,
    alignItems: 'center',
    justifyContent: 'flex-start',
    overflow: 'hidden',
    position: 'relative',
  },
  slice: {
    position: 'absolute',
    top: 0,
    left: GAUGE_RADIUS - 1,
    width: 2,
    height: GAUGE_RADIUS,
    transformOrigin: 'bottom center',
  },
  innerDisc: {
    position: 'absolute',
    left: 24,
    top: 24,
    width: GAUGE_SIZE - 48,
    height: GAUGE_SIZE - 48,
    borderRadius: INNER_RADIUS,
  },
  bottomMask: {
    position: 'absolute',
    top: GAUGE_RADIUS,
    left: 0,
    width: GAUGE_SIZE,
    height: GAUGE_RADIUS,
  },
  needle: {
    position: 'absolute',
    left: GAUGE_RADIUS,
    top: 16,
    width: 4,
    height: GAUGE_RADIUS - 16,
    borderRadius: 2,
    transformOrigin: 'bottom center',
  },
  centerLabel: {
    position: 'absolute',
    top: GAUGE_RADIUS - 44,
    width: GAUGE_SIZE,
    alignItems: 'center',
  },
  score: { fontSize: 40, fontWeight: '700' },
  legend: { flexDirection: 'row', gap: 16, marginTop: 8 },
  legendItem: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  legendDot: { width: 10, height: 10, borderRadius: 5 },
  legendText: { fontSize: 12 },
});

export default RiskMeterGauge;
