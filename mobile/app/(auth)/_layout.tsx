import { Stack } from 'expo-router';

export default function AuthLayout(): React.ReactElement {
  return (
    <Stack screenOptions={{ headerShown: false }}>
      <Stack.Screen name="sign-in" />
      <Stack.Screen name="sign-up" />
    </Stack>
  );
}
