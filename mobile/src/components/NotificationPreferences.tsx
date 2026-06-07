/**
 * NotificationPreferences — per-category notification toggles.
 *
 * Token-driven styling (no raw hex). Switch track/thumb colors come from theme.
 *
 * TODO: persist to backend via PATCH /api/users/me/preferences once that
 * endpoint exists. Parent owns state for now.
 */

import { StyleSheet, Switch, View } from 'react-native';
import type { ViewStyle } from 'react-native';

import { useTheme } from '../theme';
import { Text } from '../ui';

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
  const theme = useTheme();

  const listStyle: ViewStyle = {
    backgroundColor: theme.colors.surfaceAlt,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.colors.border,
    borderRadius: theme.radii.md,
    overflow: 'hidden',
  };

  return (
    <View style={listStyle}>
      {ROWS.map((row, i) => {
        const rowStyle: ViewStyle = {
          flexDirection: 'row',
          alignItems: 'center',
          paddingVertical: theme.spacing(3),
          paddingHorizontal: theme.spacing(4),
          gap: theme.spacing(3),
          borderBottomWidth: i < ROWS.length - 1 ? StyleSheet.hairlineWidth : 0,
          borderBottomColor: theme.colors.border,
        };
        return (
          <View key={row.key} style={rowStyle}>
            <View style={styles.textCol}>
              <Text variant="label">{row.label}</Text>
              <Text variant="caption" color="secondary">
                {row.sub}
              </Text>
            </View>
            <Switch
              value={value[row.key]}
              onValueChange={(v) => onChange(row.key, v)}
              accessibilityLabel={row.label}
              trackColor={{
                false: theme.colors.border,
                true: theme.colors.accent,
              }}
              thumbColor={theme.colors.surface}
              ios_backgroundColor={theme.colors.border}
            />
          </View>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  textCol: {
    flex: 1,
    gap: 2,
  },
});
