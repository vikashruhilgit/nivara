import { Link, useRouter } from 'expo-router';
import { useState } from 'react';
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';

import { getApiErrorMessage } from '../../src/api/client';
import { useAuthStore } from '../../src/store/auth';

export default function ResetPasswordScreen(): React.ReactElement {
  const resetPassword = useAuthStore((s) => s.resetPassword);
  const router = useRouter();
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
    <KeyboardAvoidingView
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      style={styles.container}
    >
      <View style={styles.form}>
        <Text style={styles.title}>Set a new password</Text>

        <TextInput
          accessibilityLabel="Reset code"
          placeholder="Reset code"
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
          secureTextEntry
          autoComplete="password-new"
          style={styles.input}
          value={newPassword}
          onChangeText={setNewPassword}
          editable={!busy}
        />
        <Text style={styles.hint}>Password must be at least 8 characters.</Text>

        {error && <Text style={styles.error}>{error}</Text>}

        <Pressable
          accessibilityRole="button"
          disabled={disabled}
          onPress={handleSubmit}
          style={({ pressed }) => [
            styles.btn,
            (pressed || disabled) && styles.btnDisabled,
          ]}
        >
          {busy ? (
            <ActivityIndicator color="#fff" />
          ) : (
            <Text style={styles.btnText}>Reset password</Text>
          )}
        </Pressable>

        <Link href="/(auth)/sign-in" style={styles.link}>
          Back to sign in
        </Link>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, justifyContent: 'center', padding: 24, backgroundColor: '#fff' },
  form: { gap: 12 },
  title: { fontSize: 24, fontWeight: '700', marginBottom: 16 },
  input: {
    borderWidth: 1,
    borderColor: '#d0d7de',
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 10,
    fontSize: 16,
  },
  btn: {
    backgroundColor: '#1f6feb',
    paddingVertical: 12,
    borderRadius: 8,
    alignItems: 'center',
    marginTop: 8,
  },
  btnDisabled: { opacity: 0.5 },
  btnText: { color: '#fff', fontSize: 16, fontWeight: '600' },
  link: { color: '#1f6feb', marginTop: 12, textAlign: 'center' },
  error: { color: '#cf222e', fontSize: 14 },
  hint: { color: '#57606a', fontSize: 13 },
});
