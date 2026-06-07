import { Link } from 'expo-router';
import { useMemo, useState } from 'react';
import { KeyboardAvoidingView, Platform, TextInput, View } from 'react-native';
import type { TextStyle, ViewStyle } from 'react-native';

import { getApiErrorMessage } from '../../src/api/client';
import { useAuthStore } from '../../src/store/auth';
import { useTheme } from '../../src/theme';
import type { Theme } from '../../src/theme';
import { Button, Screen, Surface, Text } from '../../src/ui';

export default function SignInScreen(): React.ReactElement {
  const signIn = useAuthStore((s) => s.signIn);
  const theme = useTheme();
  const styles = useMemo(() => makeStyles(theme), [theme]);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(): Promise<void> {
    setBusy(true);
    setError(null);
    try {
      await signIn(email.trim(), password);
    } catch (err) {
      setError(getApiErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const disabled = busy || !email || !password;

  return (
    <Screen padded style={styles.content}>
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        style={styles.flex}
      >
        <View style={styles.inner}>
          <View style={styles.hero}>
            <View style={styles.brandMark}>
              <Text variant="title" color="onAccent" weight="700">
                iQ
              </Text>
            </View>
            <Text variant="h1" weight="700">
              Welcome back
            </Text>
            <Text variant="body" color="secondary" style={styles.subtitle}>
              Sign in to InvestIQ to view your portfolio and recommendations.
            </Text>
          </View>

          <Surface variant="auto" elevation="md" style={styles.card}>
            <View style={styles.form}>
              <TextInput
                accessibilityLabel="Email"
                placeholder="email@example.com"
                placeholderTextColor={theme.colors.textTertiary}
                keyboardType="email-address"
                autoCapitalize="none"
                autoComplete="email"
                style={styles.input}
                value={email}
                onChangeText={setEmail}
                editable={!busy}
              />
              <TextInput
                accessibilityLabel="Password"
                placeholder="Password"
                placeholderTextColor={theme.colors.textTertiary}
                secureTextEntry
                autoComplete="password"
                style={styles.input}
                value={password}
                onChangeText={setPassword}
                editable={!busy}
              />

              {error && (
                <Text variant="caption" color="negative">
                  {error}
                </Text>
              )}

              <Button
                title="Sign in"
                onPress={handleSubmit}
                disabled={disabled}
                loading={busy}
                accessibilityLabel="Sign in"
              />

              <Link href="/(auth)/forgot-password" style={styles.link}>
                <Text variant="label" color="accent">
                  Forgot password?
                </Text>
              </Link>
            </View>
          </Surface>

          <Link href="/(auth)/sign-up" style={styles.footerLink}>
            <Text variant="body" color="secondary">
              Don&apos;t have an account?{' '}
            </Text>
            <Text variant="label" color="accent">
              Sign up
            </Text>
          </Link>
        </View>
      </KeyboardAvoidingView>
    </Screen>
  );
}

function makeStyles(theme: Theme): {
  flex: ViewStyle;
  content: ViewStyle;
  inner: ViewStyle;
  hero: ViewStyle;
  brandMark: ViewStyle;
  subtitle: TextStyle;
  card: ViewStyle;
  form: ViewStyle;
  input: TextStyle;
  link: TextStyle;
  footerLink: TextStyle;
} {
  return {
    flex: { flex: 1 },
    content: { flexGrow: 1, justifyContent: 'center' },
    inner: { gap: theme.spacing(6) },
    hero: { gap: theme.spacing(2) },
    brandMark: {
      width: 56,
      height: 56,
      borderRadius: theme.radii.lg,
      backgroundColor: theme.colors.accent,
      alignItems: 'center',
      justifyContent: 'center',
      marginBottom: theme.spacing(2),
    },
    subtitle: { marginTop: theme.spacing(1) },
    card: { padding: theme.spacing(5) },
    form: { gap: theme.spacing(3) },
    input: {
      backgroundColor: theme.colors.surfaceAlt,
      borderColor: theme.colors.border,
      borderWidth: 1,
      borderRadius: theme.radii.md,
      color: theme.colors.textPrimary,
      paddingHorizontal: theme.spacing(3),
      paddingVertical: theme.spacing(3),
      fontSize: theme.typography.body.fontSize,
      minHeight: 48,
    },
    link: { alignSelf: 'center', paddingVertical: theme.spacing(2) },
    footerLink: {
      alignSelf: 'center',
      flexDirection: 'row',
      alignItems: 'center',
      paddingVertical: theme.spacing(2),
    },
  };
}
