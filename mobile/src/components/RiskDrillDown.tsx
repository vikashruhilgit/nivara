/**
 * RiskDrillDown - modal showing the component breakdown of the Risk Meter.
 *
 * Rows: Concentration, VaR, Drawdown, Events (whatever the backend returns).
 * Each row shows name, score (0-100), weight, and detail key/value pairs.
 */

import React from 'react';
import {
  ActivityIndicator,
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';

import { RiskComponent, useRiskMeterDrilldown } from '../hooks/useRiskMeter';
import { zoneColor } from './RiskMeterGauge';

const COLOR_MUTED = '#57606a';
const COLOR_BORDER = '#d0d7de';

export interface RiskDrillDownProps {
  visible: boolean;
  onClose: () => void;
}

function formatDetailValue(value: unknown): string {
  if (value === null || value === undefined) return '-';
  if (typeof value === 'number') {
    return Number.isInteger(value) ? value.toString() : value.toFixed(2);
  }
  if (typeof value === 'string' || typeof value === 'boolean') {
    return String(value);
  }
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function ComponentRow({
  component,
}: {
  component: RiskComponent;
}): React.ReactElement {
  const score = Math.round(component.score);
  const color = zoneColor(score);
  const detailEntries = component.detail ? Object.entries(component.detail) : [];
  return (
    <View style={styles.row}>
      <View style={styles.rowHeader}>
        <View style={{ flex: 1 }}>
          <Text style={styles.rowName}>{component.name}</Text>
          <Text style={styles.rowSub}>
            Weight {(component.weight * 100).toFixed(0)}%
          </Text>
        </View>
        <View style={[styles.scoreBadge, { backgroundColor: color }]}>
          <Text style={styles.scoreBadgeText}>{score}</Text>
        </View>
      </View>
      {detailEntries.length > 0 ? (
        <View style={styles.detailBlock}>
          {detailEntries.map(([k, v]) => (
            <View key={k} style={styles.detailRow}>
              <Text style={styles.detailKey}>{k}</Text>
              <Text style={styles.detailValue}>{formatDetailValue(v)}</Text>
            </View>
          ))}
        </View>
      ) : null}
    </View>
  );
}

export function RiskDrillDown({
  visible,
  onClose,
}: RiskDrillDownProps): React.ReactElement {
  const query = useRiskMeterDrilldown();

  return (
    <Modal
      visible={visible}
      animationType="slide"
      presentationStyle="pageSheet"
      onRequestClose={onClose}
    >
      <View style={styles.container}>
        <View style={styles.header}>
          <Text style={styles.title}>Risk Breakdown</Text>
          <Pressable
            onPress={onClose}
            accessibilityRole="button"
            accessibilityLabel="Close risk breakdown"
            style={styles.closeBtn}
          >
            <Text style={styles.closeText}>Close</Text>
          </Pressable>
        </View>

        {query.isPending ? (
          <View style={styles.centered}>
            <ActivityIndicator size="large" />
          </View>
        ) : query.error || !query.data ? (
          <View style={styles.centered}>
            <Text style={styles.sub}>
              Risk breakdown unavailable. Pull to retry.
            </Text>
          </View>
        ) : (
          <ScrollView contentContainerStyle={styles.content}>
            <View style={styles.summaryCard}>
              <Text style={styles.sub}>Overall score</Text>
              <Text
                style={[
                  styles.overallScore,
                  { color: zoneColor(query.data.overall_score) },
                ]}
              >
                {Math.round(query.data.overall_score)}
              </Text>
              {query.data.staleness !== 'fresh' ? (
                <Text style={styles.stale}>
                  {query.data.staleness === 'very_stale' ? 'Very stale' : 'Stale'}
                  {query.data.stale_reason ? ` - ${query.data.stale_reason}` : ''}
                </Text>
              ) : null}
            </View>
            {query.data.components.map((c) => (
              <ComponentRow key={c.name} component={c} />
            ))}
          </ScrollView>
        )}
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#ffffff' },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: 16,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: COLOR_BORDER,
  },
  title: { flex: 1, fontSize: 18, fontWeight: '700' },
  closeBtn: { paddingHorizontal: 8, paddingVertical: 4 },
  closeText: { color: '#0969da', fontSize: 16 },
  centered: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: 32,
  },
  content: { padding: 16, gap: 12 },
  summaryCard: {
    backgroundColor: '#f6f8fa',
    borderRadius: 12,
    padding: 16,
    alignItems: 'center',
    marginBottom: 8,
  },
  overallScore: { fontSize: 36, fontWeight: '700', marginTop: 4 },
  stale: { marginTop: 6, fontSize: 12, color: '#bf8700' },
  row: {
    backgroundColor: '#ffffff',
    borderRadius: 12,
    padding: 16,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: COLOR_BORDER,
  },
  rowHeader: { flexDirection: 'row', alignItems: 'center' },
  rowName: { fontSize: 16, fontWeight: '600' },
  rowSub: { fontSize: 12, color: COLOR_MUTED, marginTop: 2 },
  scoreBadge: {
    minWidth: 44,
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 8,
    alignItems: 'center',
  },
  scoreBadgeText: { color: '#ffffff', fontSize: 16, fontWeight: '700' },
  detailBlock: {
    marginTop: 12,
    paddingTop: 12,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: COLOR_BORDER,
    gap: 4,
  },
  detailRow: { flexDirection: 'row', justifyContent: 'space-between' },
  detailKey: { fontSize: 13, color: COLOR_MUTED },
  detailValue: { fontSize: 13, color: '#24292f' },
  sub: { fontSize: 13, color: COLOR_MUTED },
});

export default RiskDrillDown;
