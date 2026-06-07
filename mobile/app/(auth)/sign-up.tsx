import { Link } from 'expo-router';
import { useMemo, useState } from 'react';
import { KeyboardAvoidingView, Platform, TextInput, View } from 'react-native';
import type { TextStyle, ViewStyle } from 'react-native';

import { getApiErrorMessage } from '../../src/api/client';
import { useAuthStore } from '../../src/store/auth';
import { useTheme } from '../../src/theme';
import type { Theme } from '../../src/theme';
import { Button, Screen, Surface, Text } from '../../src/ui';

export default function SignUpScreen(): React.ReactElement {
  const signUp = useAuthStore((s) => s.signUp);
  const theme = useTheme();
  const styles = useMemo(() => makeStyles(theme), [theme]);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [fullName, setFullName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(): Promise<void> {
    setBusy(true);
    setError(null);
    try {
      await signUp(email.trim(), password, fullName.trim() || undefined);
    } catch (err) {
      setError(getApiErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const disabled = busy || !email || !password;

  return (
    <Screen padded scroll contentContainerStyle={styles.content}>
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
              Create your account
            </Text>
            <Text variant="body" color="secondary" style={styles.subtitle}>
              Join InvestIQ to connect your broker and start investing smarter.
            </Text>
          </View>

          <Surface variant="auto" elevation="md" style={styles.card}>
            <View style={styles.form}>
              <TextInput
                accessibilityLabel="Full name"
                placeholder="Full name (optional)"
                placeholderTextColor={theme.colors.textTertiary}
                autoCapitalize="words"
                style={styles.input}
                value={fullName}
                onChangeText={setFullName}
                editable={!busy}
              />
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
                autoComplete="password-new"
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
                title="Create account"
                onPress={handleSubmit}
                disabled={disabled}
                loading={busy}
                accessibilityLabel="Create account"
              />
            </View>
          </Surface>

          <Link href="/(auth)/sign-in" style={styles.footerLink}>
            <Text variant="body" color="secondary">
              Already have an account?{' '}
            </Text>
            <Text variant="label" color="accent">
              Sign in
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
    footerLink: {
      alignSelf: 'center',
      flexDirection: 'row',
      alignItems: 'center',
      paddingVertical: theme.spacing(2),
    },
  };
}
