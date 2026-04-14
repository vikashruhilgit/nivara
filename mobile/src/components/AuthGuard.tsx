/**
 * AuthGuard — redirects based on auth state.
 *
 * - While hydrating: shows a loader (no redirect).
 * - Unauthenticated + not in /(auth) group: redirect to /(auth)/sign-in.
 * - Authenticated + in /(auth) group: redirect to /(tabs)/portfolio.
 */

import { Redirect, useSegments } from 'expo-router';
import { ActivityIndicator, StyleSheet, View } from 'react-native';

import { useAuthStore } from '../store/auth';

export function AuthGuard({ children }: { children: React.ReactNode }): React.ReactElement {
  const status = useAuthStore((s) => s.status);
  const segments = useSegments();
  const inAuthGroup = segments[0] === '(auth)';

  if (status === 'idle' || status === 'hydrating') {
    return (
      <View style={styles.loader}>
        <ActivityIndicator size="large" />
      </View>
    );
  }

  if (status === 'unauthenticated' && !inAuthGroup) {
    return <Redirect href="/(auth)/sign-in" />;
  }

  if (status === 'authenticated' && inAuthGroup) {
    return <Redirect href="/(tabs)/portfolio" />;
  }

  return <>{children}</>;
}

const styles = StyleSheet.create({
  loader: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
});
