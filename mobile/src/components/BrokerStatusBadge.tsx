/**
 * BrokerStatusBadge — single broker row with status pill.
 *
 * Layout: broker name on the left, colored status pill on the right.
 * Rendering rules (M4-21 AC #7-9):
 *   - connected/synced  → green pill "Synced"    (not pressable)
 *   - expired/relogin   → yellow pill "Re-login" (pressable)
 *   - disconnected/connect → gray pill "Connect" (pressable)
 */

import { Pressable, StyleSheet, Text, View } from 'react-native';

import type { BrokerAction, BrokerStatus } from '../hooks/useBrokerStatus';

interface PillStyle {
  bg: string;
  text: string;
  label: string;
  pressable: boolean;
}

const PILL_BY_ACTION: Record<BrokerAction, PillStyle> = {
  synced: { bg: '#1a7f37', text: '#fff', label: 'Synced', pressable: false },
  relogin: { bg: '#bf8700', text: '#fff', label: 'Re-login', pressable: true },
  connect: { bg: '#57606a', text: '#fff', label: 'Connect', pressable: true },
};

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
  const pill = PILL_BY_ACTION[status.action];
  const brokerName = BROKER_DISPLAY[status.broker];

  const pillContent = (
    <View style={[styles.pill, { backgroundColor: pill.bg }]}>
      <Text style={[styles.pillText, { color: pill.text }]}>{pill.label}</Text>
    </View>
  );

  return (
    <View style={styles.row}>
      <Text style={styles.broker}>{brokerName}</Text>
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
    borderColor: '#d0d7de',
    borderRadius: 10,
    backgroundColor: '#fff',
  },
  broker: {
    fontSize: 16,
    fontWeight: '600',
    color: '#1f2328',
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
