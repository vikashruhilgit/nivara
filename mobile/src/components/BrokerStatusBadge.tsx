/**
 * BrokerStatusBadge — single broker row with status pill.
 *
 * Layout: broker name on the left, colored status pill on the right.
 * Rendering rules (M4-21 AC #7-9):
 *   - connected/synced  → positive pill "Synced"   (not pressable)
 *   - expired/relogin   → warning pill "Re-login"  (pressable)
 *   - disconnected/connect → neutral pill "Connect" (pressable)
 *
 * Colors are sourced from theme tokens (no raw hex).
 */

import { Pressable, StyleSheet, Text, View } from 'react-native';

import type { BrokerAction, BrokerStatus } from '../hooks/useBrokerStatus';
import { useTheme } from '../theme';
import type { Theme } from '../theme';

interface PillStyle {
  bg: string;
  text: string;
  label: string;
  pressable: boolean;
}

function pillByAction(theme: Theme): Record<BrokerAction, PillStyle> {
  const c = theme.colors;
  return {
    synced: { bg: c.positive, text: c.textOnAccent, label: 'Synced', pressable: false },
    relogin: { bg: c.warning, text: c.textOnAccent, label: 'Re-login', pressable: true },
    connect: { bg: c.neutral, text: c.textOnAccent, label: 'Connect', pressable: true },
  };
}

const BROKER_DISPLAY: Record<BrokerStatus['broker'], string> = {
  alpaca: 'Alpaca',
  zerodha: 'Zerodha',
};

export function BrokerStatusBadge({
  status,
  onPress,
}: {
  status: BrokerStatus;
  onPress?: () => void;
}): React.ReactElement {
  const theme = useTheme();
  const pill = pillByAction(theme)[status.action];
  const brokerName = BROKER_DISPLAY[status.broker];

  const pillContent = (
    <View style={[styles.pill, { backgroundColor: pill.bg }]}>
      <Text style={[styles.pillText, { color: pill.text }]}>{pill.label}</Text>
    </View>
  );

  return (
    <View
      style={[
        styles.row,
        {
          borderColor: theme.colors.border,
          backgroundColor: theme.colors.surface,
        },
      ]}
    >
      <Text style={[styles.broker, { color: theme.colors.textPrimary }]}>
        {brokerName}
      </Text>
      {pill.pressable ? (
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={`${brokerName} ${pill.label}`}
          onPress={onPress}
          style={({ pressed }) => [pressed && styles.pressed]}
        >
          {pillContent}
        </Pressable>
      ) : (
        pillContent
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: 12,
    borderWidth: 1,
    borderRadius: 10,
  },
  broker: {
    fontSize: 16,
    fontWeight: '600',
  },
  pill: {
    paddingVertical: 6,
    paddingHorizontal: 12,
    borderRadius: 999,
    alignItems: 'center',
    justifyContent: 'center',
  },
  pillText: {
    fontSize: 13,
    fontWeight: '600',
  },
  pressed: {
    opacity: 0.7,
  },
});
