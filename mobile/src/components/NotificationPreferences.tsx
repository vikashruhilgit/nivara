/**
 * NotificationPreferences — per-category notification toggles.
 *
 * TODO: persist to backend via PATCH /api/users/me/preferences once that
 * endpoint exists. Parent owns state for now.
 */

import { StyleSheet, Switch, Text, View } from 'react-native';

export interface NotificationPrefs {
  marketAlerts: boolean;
  dailySummary: boolean;
  recommendations: boolean;
}

export type NotificationPrefKey = keyof NotificationPrefs;

const ROWS: { key: NotificationPrefKey; label: string; sub: string }[] = [
  {
    key: 'marketAlerts',
    label: 'Market alerts',
    sub: 'Price moves and risk-meter spikes',
  },
  {
    key: 'dailySummary',
    label: 'Daily summary',
    sub: 'Once-a-day portfolio digest',
  },
  {
    key: 'recommendations',
    label: 'AI recommendations',
    sub: 'New buy / sell signals for your holdings',
  },
];

export function NotificationPreferences({
  value,
  onChange,
}: {
  value: NotificationPrefs;
  onChange: (key: NotificationPrefKey, v: boolean) => void;
}): React.ReactElement {
  return (
    <View style={styles.list}>
      {ROWS.map((row, i) => (
        <View
          key={row.key}
          style={[styles.row, i < ROWS.length - 1 && styles.rowBorder]}
        >
          <View style={styles.textCol}>
            <Text style={styles.label}>{row.label}</Text>
            <Text style={styles.sub}>{row.sub}</Text>
          </View>
          <Switch
            value={value[row.key]}
            onValueChange={(v) => onChange(row.key, v)}
            accessibilityLabel={row.label}
          />
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  list: {
    backgroundColor: '#fff',
    borderWidth: 1,
    borderColor: '#d0d7de',
    borderRadius: 12,
    overflow: 'hidden',
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 12,
    paddingHorizontal: 16,
    gap: 12,
  },
  rowBorder: {
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: '#d0d7de',
  },
  textCol: {
    flex: 1,
    gap: 2,
  },
  label: {
    fontSize: 15,
    fontWeight: '600',
    color: '#1f2328',
  },
  sub: {
    fontSize: 12,
    color: '#57606a',
  },
});
