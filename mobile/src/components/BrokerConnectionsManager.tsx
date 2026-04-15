/**
 * BrokerConnectionsManager — list of broker status badges on the Settings screen.
 *
 * Pressing a pressable badge (Connect / Re-login) launches the existing
 * BrokerConnect OAuth flow for that broker.
 */

import { useState } from 'react';
import { ActivityIndicator, StyleSheet, Text, View } from 'react-native';

import { useBrokerStatus, type BrokerStatus } from '../hooks/useBrokerStatus';
import { BrokerConnect } from './BrokerConnect';
import { BrokerStatusBadge } from './BrokerStatusBadge';

export function BrokerConnectionsManager(): React.ReactElement {
  const query = useBrokerStatus();
  const [connecting, setConnecting] = useState<BrokerStatus['broker'] | null>(null);

  if (query.isPending) {
    return (
      <View style={styles.centered}>
        <ActivityIndicator />
      </View>
    );
  }

  if (query.error) {
    return (
      <View style={styles.centered}>
        <Text style={styles.sub}>Unable to load broker status.</Text>
      </View>
    );
  }

  const statuses = query.data ?? [];

  return (
    <View style={styles.list}>
      {statuses.map((s) => (
        <View key={s.broker} style={styles.item}>
          <BrokerStatusBadge
            status={s}
            onPress={() => setConnecting(s.broker)}
          />
          {connecting === s.broker ? (
            <View style={styles.connectHost}>
              <BrokerConnect
                broker={s.broker}
                onConnected={() => {
                  setConnecting(null);
                  void query.refetch();
                }}
              />
            </View>
          ) : null}
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  list: {
    gap: 12,
  },
  item: {
    gap: 8,
  },
  connectHost: {
    paddingHorizontal: 4,
  },
  centered: {
    alignItems: 'center',
    paddingVertical: 16,
  },
  sub: {
    fontSize: 13,
    color: '#57606a',
  },
});
