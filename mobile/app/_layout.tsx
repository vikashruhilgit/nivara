import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useEffect, useMemo } from 'react';

import { AuthGuard } from '../src/components/AuthGuard';
import { configureAuthClient, useAuthStore } from '../src/store/auth';
import { useThemeStore } from '../src/store/theme';
import { ThemeProvider, useTheme } from '../src/theme';

function ThemedRoot(): React.ReactElement {
  const theme = useTheme();

  return (
    <>
      {/* light scheme → dark status-bar content; dark scheme → light content */}
      <StatusBar style={theme.scheme === 'dark' ? 'light' : 'dark'} />
      <AuthGuard>
        <Stack screenOptions={{ headerShown: false }}>
          <Stack.Screen name="(auth)" />
          <Stack.Screen name="(tabs)" />
        </Stack>
      </AuthGuard>
    </>
  );
}

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
  const hydrateTheme = useThemeStore((s) => s.hydrate);

  useEffect(() => {
    configureAuthClient();
    void hydrate();
    void hydrateTheme();
  }, [hydrate, hydrateTheme]);

  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <ThemedRoot />
      </ThemeProvider>
    </QueryClientProvider>
  );
}
