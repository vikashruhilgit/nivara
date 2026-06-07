/**
 * RiskDrillDown - modal showing the component breakdown of the Risk Meter.
 *
 * Rows: Concentration, VaR, Drawdown, Events (whatever the backend returns).
 * Each row shows name, score (0-100), weight, and detail key/value pairs.
 */

import React, { useMemo } from 'react';
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
import type { Theme } from '../theme';
import { useTheme } from '../theme';
import { zoneColor } from './RiskMeterGauge';

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
  const theme = useTheme();
  const styles = useMemo(() => makeStyles(theme), [theme]);
  const score = Math.round(component.score);
  const color = zoneColor(theme, score);
  const detailEntries = component.detail ? Object.entries(component.detail) : [];
  return (
    <View style={styles.row}>
      <View style={styles.rowHeader}>
        <View style={styles.flex1}>
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
  const theme = useTheme();
  const styles = useMemo(() => makeStyles(theme), [theme]);
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
            <ActivityIndicator size="large" color={theme.colors.accent} />
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
                  { color: zoneColor(theme, query.data.overall_score) },
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

function makeStyles(theme: Theme) {
  return StyleSheet.create({
    container: { flex: 1, backgroundColor: theme.colors.background },
    flex1: { flex: 1 },
    header: {
      flexDirection: 'row',
      alignItems: 'center',
      padding: theme.spacing(4),
      borderBottomWidth: StyleSheet.hairlineWidth,
      borderBottomColor: theme.colors.border,
    },
    title: {
      flex: 1,
      fontSize: theme.typography.title.fontSize,
      fontWeight: '700',
      color: theme.colors.textPrimary,
    },
    closeBtn: { paddingHorizontal: theme.spacing(2), paddingVertical: theme.spacing(1) },
    closeText: { color: theme.colors.accent, fontSize: 16 },
    centered: {
      flex: 1,
      alignItems: 'center',
      justifyContent: 'center',
      padding: theme.spacing(8),
    },
    content: { padding: theme.spacing(4), gap: theme.spacing(3) },
    summaryCard: {
      backgroundColor: theme.colors.surfaceAlt,
      borderRadius: theme.radii.lg,
      padding: theme.spacing(4),
      alignItems: 'center',
      marginBottom: theme.spacing(2),
    },
    overallScore: { fontSize: 36, fontWeight: '700', marginTop: theme.spacing(1) },
    stale: { marginTop: 6, fontSize: 12, color: theme.colors.warning },
    row: {
      backgroundColor: theme.colors.surface,
      borderRadius: theme.radii.lg,
      padding: theme.spacing(4),
      borderWidth: StyleSheet.hairlineWidth,
      borderColor: theme.colors.border,
    },
    rowHeader: { flexDirection: 'row', alignItems: 'center' },
    rowName: { fontSize: 16, fontWeight: '600', color: theme.colors.textPrimary },
    rowSub: { fontSize: 12, color: theme.colors.textSecondary, marginTop: 2 },
    scoreBadge: {
      minWidth: 44,
      paddingHorizontal: theme.spacing(2.5),
      paddingVertical: theme.spacing(1.5),
      borderRadius: theme.radii.sm,
      alignItems: 'center',
    },
    scoreBadgeText: { color: theme.colors.textOnAccent, fontSize: 16, fontWeight: '700' },
    detailBlock: {
      marginTop: theme.spacing(3),
      paddingTop: theme.spacing(3),
      borderTopWidth: StyleSheet.hairlineWidth,
      borderTopColor: theme.colors.border,
      gap: 4,
    },
    detailRow: { flexDirection: 'row', justifyContent: 'space-between' },
    detailKey: { fontSize: 13, color: theme.colors.textSecondary },
    detailValue: { fontSize: 13, color: theme.colors.textPrimary },
    sub: { fontSize: 13, color: theme.colors.textSecondary },
  });
}

export default RiskDrillDown;
