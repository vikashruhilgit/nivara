import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { BrokerConnect } from '../../src/components/BrokerConnect';
import { useAuthStore } from '../../src/store/auth';

export default function SettingsScreen(): React.ReactElement {
  const user = useAuthStore((s) => s.user);
  const signOut = useAuthStore((s) => s.signOut);

  return (
    <ScrollView contentContainerStyle={styles.container}>
      <View style={styles.section}>
        <Text style={styles.sectionTitle}>Account</Text>
        <Text style={styles.value}>{user?.email ?? 'Unknown user'}</Text>
        {user?.full_name ? <Text style={styles.sub}>{user.full_name}</Text> : null}
      </View>

      <View style={styles.section}>
        <Text style={styles.sectionTitle}>Broker</Text>
        <Text style={styles.sub}>
          Link your brokerage account to sync positions and place trades from InvestIQ.
        </Text>
        <BrokerConnect broker="alpaca" />
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
