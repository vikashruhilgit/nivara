/**
 * AuthGuard — redirects based on auth state.
 *
 * IMPORTANT (expo-router): the root layout must mount its navigator (<Stack>)
 * on the first render. So this guard must NOT replace `children` with a loader
 * or <Redirect> — doing so prevents the navigator from mounting and throws
 * "Attempted to navigate before mounting the Root Layout component."
 *
 * Instead we always render `children` (the navigator) and perform redirects
 * imperatively in a post-mount effect:
 * - While hydrating: do nothing (the index/screens render null until settled).
 * - Unauthenticated + not in /(auth) group: redirect to /(auth)/sign-in.
 * - Authenticated + in /(auth) group: redirect to /(tabs)/portfolio.
 */

import { useRouter, useSegments } from 'expo-router';
import { useEffect } from 'react';

import { useAuthStore } from '../store/auth';

export function AuthGuard({ children }: { children: React.ReactNode }): React.ReactElement {
  const status = useAuthStore((s) => s.status);
  const segments = useSegments();
  const router = useRouter();

  useEffect(() => {
    // Wait until auth state has settled before navigating.
    if (status === 'idle' || status === 'hydrating') {
      return;
    }

    const inAuthGroup = segments[0] === '(auth)';

    if (status === 'unauthenticated' && !inAuthGroup) {
      router.replace('/(auth)/sign-in');
    } else if (status === 'authenticated' && inAuthGroup) {
      router.replace('/(tabs)/portfolio');
    }
  }, [status, segments, router]);

  return <>{children}</>;
}
