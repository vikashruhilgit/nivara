import { Link } from 'expo-router';
import { useMemo, useState } from 'react';
import { KeyboardAvoidingView, Platform, TextInput, View } from 'react-native';
import type { TextStyle, ViewStyle } from 'react-native';

import { getApiErrorMessage } from '../../src/api/client';
import { useAuthStore } from '../../src/store/auth';
import { useTheme } from '../../src/theme';
import type { Theme } from '../../src/theme';
import { Button, Screen, Surface, Text } from '../../src/ui';

const CONFIRMATION =
  'If that email exists, a reset link has been sent. Check your email for the code.';

export default function ForgotPasswordScreen(): React.ReactElement {
  const requestPasswordReset = useAuthStore((s) => s.requestPasswordReset);
  const theme = useTheme();
  const styles = useMemo(() => makeStyles(theme), [theme]);
  const [email, setEmail] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);

  async function handleSubmit(): Promise<void> {
    setBusy(true);
    setError(null);
    try {
      await requestPasswordReset(email.trim());
      setSent(true);
    } catch (err) {
      setError(getApiErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const disabled = busy || !email;

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
              Reset your password
            </Text>
            <Text variant="body" color="secondary" style={styles.subtitle}>
              Enter the email tied to your account and we&apos;ll send a reset
              code.
            </Text>
          </View>

          <Surface variant="auto" elevation="md" style={styles.card}>
            <View style={styles.form}>
              {sent ? (
                <>
                  <Text variant="body" color="positive">
                    {CONFIRMATION}
                  </Text>
                  <Link href="/(auth)/reset-password" style={styles.link}>
                    <Text variant="label" color="accent">
                      Enter your reset code
                    </Text>
                  </Link>
                </>
              ) : (
                <>
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

                  {error && (
                    <Text variant="caption" color="negative">
                      {error}
                    </Text>
                  )}

                  <Button
                    title="Send reset link"
                    onPress={handleSubmit}
                    disabled={disabled}
                    loading={busy}
                    accessibilityLabel="Send reset link"
                  />
                </>
              )}
            </View>
          </Surface>

          <Link href="/(auth)/sign-in" style={styles.footerLink}>
            <Text variant="label" color="accent">
              Back to sign in
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
      paddingVertical: theme.spacing(2),
    },
  };
}
