import { Redirect } from 'expo-router';
import { ActivityIndicator, StyleSheet, View } from 'react-native';

import { useAuthStore } from '../src/store/auth';
import { useTheme } from '../src/theme';
import { Screen } from '../src/ui';

/**
 * Root redirect — sends users to the correct group based on auth state.
 * While auth is still settling (idle/hydrating) we render a themed full-screen
 * loading state instead of null; once settled we redirect.
 */
export default function Index(): React.ReactElement {
  const status = useAuthStore((s) => s.status);
  const theme = useTheme();

  if (status === 'authenticated') return <Redirect href="/(tabs)/portfolio" />;
  if (status === 'unauthenticated') return <Redirect href="/(auth)/sign-in" />;

  return (
    <Screen>
      <View style={styles.center}>
        <ActivityIndicator size="large" color={theme.colors.accent} />
      </View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
});
