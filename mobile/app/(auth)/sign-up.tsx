import { Link } from 'expo-router';
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

export default function SignUpScreen(): React.ReactElement {
  const signUp = useAuthStore((s) => s.signUp);
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
    <KeyboardAvoidingView
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      style={styles.container}
    >
      <View style={styles.form}>
        <Text style={styles.title}>Create your InvestIQ account</Text>

        <TextInput
          accessibilityLabel="Full name"
          placeholder="Full name (optional)"
          autoCapitalize="words"
          style={styles.input}
          value={fullName}
          onChangeText={setFullName}
          editable={!busy}
        />
        <TextInput
          accessibilityLabel="Email"
          placeholder="email@example.com"
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
          secureTextEntry
          autoComplete="password-new"
          style={styles.input}
          value={password}
          onChangeText={setPassword}
          editable={!busy}
        />

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
          {busy ? <ActivityIndicator color="#fff" /> : <Text style={styles.btnText}>Create account</Text>}
        </Pressable>

        <Link href="/(auth)/sign-in" style={styles.link}>
          Already have an account? Sign in
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
});
