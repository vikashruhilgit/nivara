import { Redirect } from 'expo-router';

import { useAuthStore } from '../src/store/auth';

/**
 * Root redirect — sends users to the correct group based on auth state.
 * The AuthGuard in `_layout.tsx` handles the hydration case; this component
 * just picks a target once `status` is settled.
 */
export default function Index(): React.ReactElement | null {
  const status = useAuthStore((s) => s.status);
  if (status === 'authenticated') return <Redirect href="/(tabs)/portfolio" />;
  if (status === 'unauthenticated') return <Redirect href="/(auth)/sign-in" />;
  return null;
}
