import { useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { BrokerConnectionsManager } from '../../src/components/BrokerConnectionsManager';
import { CurrencyToggle, type BaseCurrency } from '../../src/components/CurrencyToggle';
import {
  NotificationPreferences,
  type NotificationPrefKey,
  type NotificationPrefs,
} from '../../src/components/NotificationPreferences';
import { useAuthStore } from '../../src/store/auth';

export default function SettingsScreen(): React.ReactElement {
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
    <ScrollView contentContainerStyle={styles.container}>
      <View style={styles.section}>
        <Text style={styles.sectionTitle}>Account</Text>
        <Text style={styles.value}>{user?.email ?? 'Unknown user'}</Text>
        {user?.full_name ? <Text style={styles.sub}>{user.full_name}</Text> : null}
      </View>

      <View style={styles.section}>
        <Text style={styles.sectionTitle}>Display</Text>
        <CurrencyToggle value={baseCurrency} onChange={setBaseCurrency} />
      </View>

      <View style={styles.section}>
        <Text style={styles.sectionTitle}>Notifications</Text>
        <NotificationPreferences value={prefs} onChange={setPref} />
      </View>

      <View style={styles.section}>
        <Text style={styles.sectionTitle}>Broker connections</Text>
        <BrokerConnectionsManager />
      </View>

      <View style={styles.section}>
        <Pressable
          accessibilityRole="button"
          onPress={() => void signOut()}
          style={({ pressed }) => [styles.signOut, pressed && styles.signOutPressed]}
        >
          <Text style={styles.signOutText}>Sign out</Text>
        </Pressable>
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { padding: 24, gap: 24 },
  section: { gap: 8 },
  sectionTitle: { fontSize: 13, color: '#57606a', textTransform: 'uppercase', letterSpacing: 0.5 },
  value: { fontSize: 16, fontWeight: '600' },
  sub: { fontSize: 14, color: '#57606a' },
  signOut: {
    marginTop: 8,
    paddingVertical: 12,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#cf222e',
    alignItems: 'center',
  },
  signOutPressed: { opacity: 0.6 },
  signOutText: { color: '#cf222e', fontSize: 16, fontWeight: '600' },
});
