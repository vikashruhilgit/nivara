import { useBottomTabBarHeight } from '@react-navigation/bottom-tabs';
import { useState } from 'react';
import { View } from 'react-native';

import { AppearanceSettings } from '../../src/components/AppearanceSettings';
import { BrokerConnectionsManager } from '../../src/components/BrokerConnectionsManager';
import { CurrencyToggle, type BaseCurrency } from '../../src/components/CurrencyToggle';
import {
  NotificationPreferences,
  type NotificationPrefKey,
  type NotificationPrefs,
} from '../../src/components/NotificationPreferences';
import { useAuthStore } from '../../src/store/auth';
import { useTheme } from '../../src/theme';
import { Button, Card, Screen, Text } from '../../src/ui';

export default function SettingsScreen(): React.ReactElement {
  const theme = useTheme();
  const tabBarHeight = useBottomTabBarHeight();
  const user = useAuthStore((s) => s.user);
  const signOut = useAuthStore((s) => s.signOut);

  // TODO: persist base currency via expo-secure-store or user prefs API.
  const [baseCurrency, setBaseCurrency] = useState<BaseCurrency>('USD');

  // TODO: persist via PATCH /api/users/me/preferences once backend lands.
  const [prefs, setPrefs] = useState<NotificationPrefs>({
    marketAlerts: true,
    dailySummary: true,
    recommendations: true,
  });

  const setPref = (key: NotificationPrefKey, v: boolean): void =>
    setPrefs((p) => ({ ...p, [key]: v }));

  return (
    <Screen
      scroll
      padded
      contentContainerStyle={{
        gap: theme.spacing(4),
        paddingBottom: theme.spacing(4) + tabBarHeight,
      }}
    >
      <Card>
        <View style={{ gap: theme.spacing(3) }}>
          <Text variant="label" color="secondary">
            Appearance
          </Text>
          <AppearanceSettings />
        </View>
      </Card>

      <Card>
        <View style={{ gap: theme.spacing(2) }}>
          <Text variant="label" color="secondary">
            Account
          </Text>
          <Text variant="title">{user?.email ?? 'Unknown user'}</Text>
          {user?.full_name ? (
            <Text variant="body" color="secondary">
              {user.full_name}
            </Text>
          ) : null}
        </View>
      </Card>

      <Card>
        <View style={{ gap: theme.spacing(3) }}>
          <Text variant="label" color="secondary">
            Display
          </Text>
          <CurrencyToggle value={baseCurrency} onChange={setBaseCurrency} />
        </View>
      </Card>

      <Card>
        <View style={{ gap: theme.spacing(3) }}>
          <Text variant="label" color="secondary">
            Notifications
          </Text>
          <NotificationPreferences value={prefs} onChange={setPref} />
        </View>
      </Card>

      <Card>
        <View style={{ gap: theme.spacing(3) }}>
          <Text variant="label" color="secondary">
            Broker connections
          </Text>
          <BrokerConnectionsManager />
        </View>
      </Card>

      <Button
        variant="danger"
        title="Sign out"
        onPress={() => void signOut()}
        accessibilityLabel="Sign out"
      />
    </Screen>
  );
}
