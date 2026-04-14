import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useEffect, useMemo } from 'react';

import { AuthGuard } from '../src/components/AuthGuard';
import { configureAuthClient, useAuthStore } from '../src/store/auth';

export default function RootLayout(): React.ReactElement {
  const queryClient = useMemo(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            retry: 1,
            refetchOnWindowFocus: false,
          },
        },
      }),
    [],
  );

  const hydrate = useAuthStore((s) => s.hydrate);

  useEffect(() => {
    configureAuthClient();
    void hydrate();
  }, [hydrate]);

  return (
    <QueryClientProvider client={queryClient}>
      <StatusBar style="auto" />
      <AuthGuard>
        <Stack screenOptions={{ headerShown: false }}>
          <Stack.Screen name="(auth)" />
          <Stack.Screen name="(tabs)" />
        </Stack>
      </AuthGuard>
    </QueryClientProvider>
  );
}
