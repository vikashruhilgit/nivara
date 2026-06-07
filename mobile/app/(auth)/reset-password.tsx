import { Link, useRouter } from 'expo-router';
import { useMemo, useState } from 'react';
import { KeyboardAvoidingView, Platform, TextInput, View } from 'react-native';
import type { TextStyle, ViewStyle } from 'react-native';

import { getApiErrorMessage } from '../../src/api/client';
import { useAuthStore } from '../../src/store/auth';
import { useTheme } from '../../src/theme';
import type { Theme } from '../../src/theme';
import { Button, Screen, Surface, Text } from '../../src/ui';

export default function ResetPasswordScreen(): React.ReactElement {
  const resetPassword = useAuthStore((s) => s.resetPassword);
  const router = useRouter();
  const theme = useTheme();
  const styles = useMemo(() => makeStyles(theme), [theme]);
  const [code, setCode] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(): Promise<void> {
    setBusy(true);
    setError(null);
    try {
      await resetPassword(code.trim(), newPassword);
      router.replace('/(auth)/sign-in');
    } catch (err) {
      setError(getApiErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const disabled = busy || !code || !newPassword;

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
              Set a new password
            </Text>
            <Text variant="body" color="secondary" style={styles.subtitle}>
              Enter the code from your email and choose a new password.
            </Text>
          </View>

          <Surface variant="auto" elevation="md" style={styles.card}>
            <View style={styles.form}>
              <TextInput
                accessibilityLabel="Reset code"
                placeholder="Reset code"
                placeholderTextColor={theme.colors.textTertiary}
                autoCapitalize="none"
                autoCorrect={false}
                style={styles.input}
                value={code}
                onChangeText={setCode}
                editable={!busy}
              />
              <TextInput
                accessibilityLabel="New password"
                placeholder="New password"
                placeholderTextColor={theme.colors.textTertiary}
                secureTextEntry
                autoComplete="password-new"
                style={styles.input}
                value={newPassword}
                onChangeText={setNewPassword}
                editable={!busy}
              />
              <Text variant="caption" color="secondary">
                Password must be at least 8 characters.
              </Text>

              {error && (
                <Text variant="caption" color="negative">
                  {error}
                </Text>
              )}

              <Button
                title="Reset password"
                onPress={handleSubmit}
                disabled={disabled}
                loading={busy}
                accessibilityLabel="Reset password"
              />
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
      paddingVertical: theme.spacing(2),
    },
  };
}
