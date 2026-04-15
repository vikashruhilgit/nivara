/**
 * BrokerConnect — initiates the broker OAuth flow.
 *
 * Alpaca (standard OAuth2):
 *   1. Hit GET /api/auth/broker/alpaca/connect?redirect_uri=investiq://oauth/alpaca
 *      → { redirect_url }
 *   2. Open the redirect URL via expo-web-browser's in-app browser
 *   3. Alpaca redirects back to `investiq://oauth/alpaca` with ?code=...
 *   4. POST /api/auth/broker/alpaca/callback { code, state }
 *
 * Zerodha / Kite Connect (NOT standard OAuth2 — login endpoint redirects back
 * with a `request_token` which the backend must exchange for an access_token
 * using the API secret + checksum):
 *   1. Open https://kite.zerodha.com/connect/login?api_key={KITE_API_KEY}&v=3
 *      via expo-web-browser in an auth session tied to
 *      `investiq://oauth/zerodha` (configured on the Kite developer console
 *      as the redirect URL).
 *   2. Kite redirects back with
 *      `?request_token=XXX&action=login&status=success`
 *      (or `status=error` / no token on failure).
 *   3. POST /api/brokers/zerodha/session/exchange { request_token }
 *      → { connection_id, status: 'connected' }
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

type BrokerName = 'alpaca' | 'zerodha';

interface ConnectResponse {
  redirect_url: string;
  broker: string;
}

interface CallbackResponse {
  connected: boolean;
  broker: string;
}

interface ZerodhaExchangeResponse {
  connection_id: string;
  status: string;
}

// TODO(M4-22): document EXPO_PUBLIC_KITE_API_KEY in mobile/.env.example once
// that file is added. For now it is read from the runtime env at module load.
const KITE_API_KEY: string | undefined = process.env.EXPO_PUBLIC_KITE_API_KEY;

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

function buildKiteLoginUrl(apiKey: string): string {
  return `https://kite.zerodha.com/connect/login?api_key=${encodeURIComponent(apiKey)}&v=3`;
}

export function BrokerConnect({
  broker = 'alpaca',
  onConnected,
}: {
  broker?: BrokerName;
  onConnected?: () => void;
}): React.ReactElement {
  const [busy, setBusy] = useState(false);

  async function runAlpacaFlow(): Promise<void> {
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
  }

  async function runZerodhaFlow(): Promise<void> {
    if (!KITE_API_KEY) {
      Alert.alert(
        'Zerodha not configured',
        'EXPO_PUBLIC_KITE_API_KEY is not set. Add it to your Expo env before connecting.',
      );
      return;
    }

    const redirectUri = AuthSession.makeRedirectUri({
      scheme: 'investiq',
      path: 'oauth/zerodha',
    });

    const loginUrl = buildKiteLoginUrl(KITE_API_KEY);
    const result = await WebBrowser.openAuthSessionAsync(loginUrl, redirectUri);

    if (result.type !== 'success' || !result.url) {
      if (result.type === 'cancel' || result.type === 'dismiss') return;
      Alert.alert('Zerodha connect failed', 'Authentication did not complete.');
      return;
    }

    const params = parseCallbackParams(result.url);
    if (params.status && params.status !== 'success') {
      Alert.alert('Zerodha connect failed', `Kite login returned status=${params.status}.`);
      return;
    }
    const requestToken = params.request_token;
    if (!requestToken) {
      Alert.alert('Zerodha connect failed', 'Missing request_token in callback.');
      return;
    }

    // TODO(M4-22 backend): POST /api/brokers/zerodha/session/exchange is not
    // yet implemented. The backend must call Kite's POST /session/token with
    // api_key + request_token + checksum(SHA256(api_key|request_token|api_secret))
    // to obtain the access_token, then persist a broker_connection row.
    // The mobile contract expected here: { connection_id: string, status: 'connected' }.
    const exchange = await apiPost<ZerodhaExchangeResponse, { request_token: string }>(
      '/api/brokers/zerodha/session/exchange',
      { request_token: requestToken },
    );

    if (exchange.status === 'connected') {
      Alert.alert('Connected', 'Zerodha account linked.');
      onConnected?.();
    } else {
      Alert.alert('Zerodha connect failed', `Backend returned status=${exchange.status}.`);
    }
  }

  async function handleConnect(): Promise<void> {
    setBusy(true);
    try {
      if (broker === 'zerodha') {
        await runZerodhaFlow();
      } else {
        await runAlpacaFlow();
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
