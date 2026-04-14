/**
 * BrokerConnect — initiates the Alpaca OAuth flow.
 *
 * Flow:
 *   1. Hit GET /api/auth/broker/alpaca/connect?redirect_uri=investiq://oauth/alpaca
 *      → { redirect_url }
 *   2. Open the redirect URL via expo-web-browser's in-app browser
 *   3. Alpaca redirects back to `investiq://oauth/alpaca` with ?code=...
 *      (expo-web-browser's auth session resolves when the scheme fires)
 *   4. POST /api/auth/broker/alpaca/callback { code, state }
 *
 * expo-auth-session is declared as a peer (makeRedirectUri is the
 * documented way to derive the redirect URI under the `investiq://` scheme),
 * while expo-web-browser drives the actual OAuth session — it's the
 * supported primitive in Expo SDK 52.
 */

import * as AuthSession from 'expo-auth-session';
import * as WebBrowser from 'expo-web-browser';
import { useState } from 'react';
import { ActivityIndicator, Alert, Pressable, StyleSheet, Text, View } from 'react-native';

import { apiGet, apiPost } from '../api/client';

interface ConnectResponse {
  redirect_url: string;
  broker: string;
}

interface CallbackResponse {
  connected: boolean;
  broker: string;
}

function parseCallbackParams(url: string): Record<string, string> {
  const q = url.split('?')[1];
  if (!q) return {};
  const result: Record<string, string> = {};
  for (const part of q.split('&')) {
    const [k, v = ''] = part.split('=');
    if (k) result[decodeURIComponent(k)] = decodeURIComponent(v);
  }
  return result;
}

export function BrokerConnect({
  broker = 'alpaca',
  onConnected,
}: {
  broker?: 'alpaca' | 'zerodha';
  onConnected?: () => void;
}): React.ReactElement {
  const [busy, setBusy] = useState(false);

  async function handleConnect(): Promise<void> {
    setBusy(true);
    try {
      const redirectUri = AuthSession.makeRedirectUri({
        scheme: 'investiq',
        path: `oauth/${broker}`,
      });

      const { redirect_url } = await apiGet<ConnectResponse>(
        `/api/auth/broker/${broker}/connect?redirect_uri=${encodeURIComponent(redirectUri)}`,
      );

      const result = await WebBrowser.openAuthSessionAsync(redirect_url, redirectUri);

      if (result.type !== 'success' || !result.url) {
        if (result.type === 'cancel' || result.type === 'dismiss') return;
        Alert.alert('Broker connect failed', 'Authentication did not complete.');
        return;
      }

      const params = parseCallbackParams(result.url);
      const code = params.code;
      if (!code) {
        Alert.alert('Broker connect failed', params.error ?? 'Missing authorisation code.');
        return;
      }

      const callback = await apiPost<CallbackResponse>(
        `/api/auth/broker/${broker}/callback`,
        { code, state: params.state },
      );

      if (callback.connected) {
        Alert.alert('Connected', `${broker} account linked.`);
        onConnected?.();
      } else {
        Alert.alert('Broker connect failed', 'Backend did not confirm connection.');
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'unknown error';
      Alert.alert('Broker connect failed', msg);
    } finally {
      setBusy(false);
    }
  }

  return (
    <View style={styles.container}>
      <Pressable
        accessibilityRole="button"
        onPress={handleConnect}
        disabled={busy}
        style={({ pressed }) => [styles.btn, (pressed || busy) && styles.btnPressed]}
      >
        {busy ? (
          <ActivityIndicator color="#fff" />
        ) : (
          <Text style={styles.btnText}>Connect {broker === 'alpaca' ? 'Alpaca' : 'Zerodha'}</Text>
        )}
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    marginVertical: 8,
  },
  btn: {
    backgroundColor: '#1f6feb',
    paddingVertical: 12,
    paddingHorizontal: 16,
    borderRadius: 8,
    alignItems: 'center',
  },
  btnPressed: {
    opacity: 0.7,
  },
  btnText: {
    color: '#fff',
    fontSize: 16,
    fontWeight: '600',
  },
});
