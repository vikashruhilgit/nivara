/**
 * RiskMeterGauge - half-circle (180 degree) gauge rendering a 0-100 score.
 *
 * Implemented with pure React Native Views (no SVG dependency). The needle
 * is a thin rectangle rotated from -90 (score=0) through 0 (score=50) to
 * +90 (score=100). The dial is a half-circle split into three colored
 * zones via absolutely positioned View slices behind a white inner disc.
 *
 * Color zones: 0-30 green, 31-60 yellow, 61-100 red.
 */

import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

const GAUGE_SIZE = 220;
const GAUGE_RADIUS = GAUGE_SIZE / 2;
const INNER_RADIUS = GAUGE_RADIUS - 24;

const COLOR_GREEN = '#1a7f37';
const COLOR_YELLOW = '#bf8700';
const COLOR_RED = '#cf222e';
const COLOR_MUTED = '#57606a';

export function zoneColor(score: number): string {
  if (score <= 30) return COLOR_GREEN;
  if (score <= 60) return COLOR_YELLOW;
  return COLOR_RED;
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
  const clamped = Math.max(0, Math.min(100, score));
  const needleDeg = -90 + (clamped / 100) * 180;
  const resolvedColor = color || zoneColor(clamped);

  const body = (
    <View style={styles.card}>
      <Text style={styles.title}>Risk Meter</Text>
      <View style={styles.gauge}>
        <Slice startDeg={-90} endDeg={-36} color={COLOR_GREEN} />
        <Slice startDeg={-36} endDeg={18} color={COLOR_YELLOW} />
        <Slice startDeg={18} endDeg={90} color={COLOR_RED} />
        <View style={styles.innerDisc} />
        <View style={styles.bottomMask} />
        <View
          style={[
            styles.needle,
            { transform: [{ translateX: -2 }, { rotate: `${needleDeg}deg` }] },
          ]}
        />
        <View style={styles.centerLabel} pointerEvents="none">
          <Text style={[styles.score, { color: resolvedColor }]}>
            {Math.round(clamped)}
          </Text>
          <Text style={styles.scoreSub}>/ 100</Text>
        </View>
      </View>
      <View style={styles.legend}>
        <LegendDot color={COLOR_GREEN} label="Low" />
        <LegendDot color={COLOR_YELLOW} label="Medium" />
        <LegendDot color={COLOR_RED} label="High" />
      </View>
      {onPress ? <Text style={styles.hint}>Tap for breakdown</Text> : null}
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
  return (
    <View style={styles.legendItem}>
      <View style={[styles.legendDot, { backgroundColor: color }]} />
      <Text style={styles.legendText}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: '#ffffff',
    borderRadius: 12,
    padding: 16,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: '#d0d7de',
    alignItems: 'center',
  },
  title: {
    fontSize: 14,
    color: COLOR_MUTED,
    alignSelf: 'flex-start',
    marginBottom: 8,
  },
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
    backgroundColor: '#ffffff',
  },
  bottomMask: {
    position: 'absolute',
    top: GAUGE_RADIUS,
    left: 0,
    width: GAUGE_SIZE,
    height: GAUGE_RADIUS,
    backgroundColor: '#ffffff',
  },
  needle: {
    position: 'absolute',
    left: GAUGE_RADIUS,
    top: 16,
    width: 4,
    height: GAUGE_RADIUS - 16,
    backgroundColor: '#24292f',
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
  scoreSub: { fontSize: 12, color: COLOR_MUTED, marginTop: 2 },
  legend: { flexDirection: 'row', gap: 16, marginTop: 8 },
  legendItem: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  legendDot: { width: 10, height: 10, borderRadius: 5 },
  legendText: { fontSize: 12, color: COLOR_MUTED },
  hint: { marginTop: 8, fontSize: 12, color: COLOR_MUTED },
});

export default RiskMeterGauge;
