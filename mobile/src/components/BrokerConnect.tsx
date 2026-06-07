/**
 * BrokerConnect — links a broker account to the InvestIQ user.
 *
 * Alpaca (API key credentials):
 *   The user pastes their Alpaca API Key ID + API Secret into a form. These are
 *   POSTed once to /api/auth/broker/alpaca/credentials over HTTPS; the backend
 *   verifies them and persists a broker_connection row. The credentials are held
 *   ONLY in React state for the lifetime of the form and are never written to
 *   expo-secure-store / AsyncStorage or any persistent storage on device.
 *   (The previous Alpaca OAuth /connect + /callback flow is retired — callback
 *   now returns 410.)
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
 * while expo-web-browser drives the actual Zerodha session — it's the
 * supported primitive in Expo SDK 52.
 */

import * as AuthSession from 'expo-auth-session';
import * as WebBrowser from 'expo-web-browser';
import { useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';

import { apiPost, getApiErrorMessage } from '../api/client';

type BrokerName = 'alpaca' | 'zerodha';

interface BrokerConnectionResponse {
  id: string;
  broker: string;
  account_id: string;
  status: string;
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
  const [apiKeyId, setApiKeyId] = useState('');
  const [apiSecret, setApiSecret] = useState('');

  async function submitAlpacaCredentials(): Promise<void> {
    setBusy(true);
    try {
      const resp = await apiPost<
        BrokerConnectionResponse,
        { api_key_id: string; api_secret: string }
      >('/api/auth/broker/alpaca/credentials', {
        api_key_id: apiKeyId.trim(),
        api_secret: apiSecret.trim(),
      });

      if (resp.status === 'active') {
        setApiSecret('');
        setApiKeyId('');
        Alert.alert('Connected', 'Alpaca account linked.');
        onConnected?.();
      } else {
        Alert.alert('Broker connect failed', `Backend returned status=${resp.status}.`);
      }
    } catch (err) {
      Alert.alert('Broker connect failed', getApiErrorMessage(err));
    } finally {
      setBusy(false);
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

  async function handleZerodhaConnect(): Promise<void> {
    setBusy(true);
    try {
      await runZerodhaFlow();
    } catch (err) {
      Alert.alert('Zerodha connect failed', getApiErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  if (broker === 'alpaca') {
    const canSubmit = apiKeyId.trim().length > 0 && apiSecret.trim().length > 0 && !busy;

    return (
      <View style={styles.container}>
        <Text style={styles.label}>API Key ID</Text>
        <TextInput
          style={styles.input}
          value={apiKeyId}
          onChangeText={setApiKeyId}
          editable={!busy}
          autoCapitalize="none"
          autoCorrect={false}
          placeholder="PK..."
          placeholderTextColor="#8b949e"
        />

        <Text style={styles.label}>API Secret</Text>
        <TextInput
          style={styles.input}
          value={apiSecret}
          onChangeText={setApiSecret}
          editable={!busy}
          secureTextEntry
          autoCapitalize="none"
          autoCorrect={false}
          placeholder="••••••••"
          placeholderTextColor="#8b949e"
        />

        <Pressable
          accessibilityRole="button"
          onPress={submitAlpacaCredentials}
          disabled={!canSubmit}
          style={({ pressed }) => [
            styles.btn,
            (pressed || busy) && styles.btnPressed,
            !canSubmit && styles.btnDisabled,
          ]}
        >
          {busy ? (
            <ActivityIndicator color="#fff" />
          ) : (
            <Text style={styles.btnText}>Connect Alpaca</Text>
          )}
        </Pressable>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <Pressable
        accessibilityRole="button"
        onPress={handleZerodhaConnect}
        disabled={busy}
        style={({ pressed }) => [styles.btn, (pressed || busy) && styles.btnPressed]}
      >
        {busy ? (
          <ActivityIndicator color="#fff" />
        ) : (
          <Text style={styles.btnText}>Connect Zerodha</Text>
        )}
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    marginVertical: 8,
  },
  label: {
    fontSize: 14,
    fontWeight: '600',
    color: '#c9d1d9',
    marginBottom: 4,
    marginTop: 8,
  },
  input: {
    borderWidth: 1,
    borderColor: '#30363d',
    borderRadius: 8,
    paddingVertical: 10,
    paddingHorizontal: 12,
    marginVertical: 4,
    fontSize: 16,
    color: '#c9d1d9',
  },
  btn: {
    backgroundColor: '#1f6feb',
    paddingVertical: 12,
    paddingHorizontal: 16,
    borderRadius: 8,
    alignItems: 'center',
    marginTop: 12,
  },
  btnPressed: {
    opacity: 0.7,
  },
  btnDisabled: {
    opacity: 0.5,
  },
  btnText: {
    color: '#fff',
    fontSize: 16,
    fontWeight: '600',
  },
});
