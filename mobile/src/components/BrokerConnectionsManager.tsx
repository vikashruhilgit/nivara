/**
 * BrokerConnectionsManager — list of broker status badges on the Settings screen.
 *
 * Pressing a pressable badge (Connect / Re-login) launches the existing
 * BrokerConnect OAuth flow for that broker.
 *
 * Token-driven styling (no raw hex).
 */

import { useState } from 'react';
import { ActivityIndicator, View } from 'react-native';
import type { ViewStyle } from 'react-native';

import { useBrokerStatus, type BrokerStatus } from '../hooks/useBrokerStatus';
import { useTheme } from '../theme';
import { Text } from '../ui';
import { BrokerConnect } from './BrokerConnect';
import { BrokerStatusBadge } from './BrokerStatusBadge';

export function BrokerConnectionsManager(): React.ReactElement {
  const theme = useTheme();
  const query = useBrokerStatus();
  const [connecting, setConnecting] = useState<BrokerStatus['broker'] | null>(null);

  const centered: ViewStyle = {
    alignItems: 'center',
    paddingVertical: theme.spacing(4),
  };

  if (query.isPending) {
    return (
      <View style={centered}>
        <ActivityIndicator color={theme.colors.accent} />
      </View>
    );
  }

  if (query.error) {
    return (
      <View style={centered}>
        <Text variant="caption" color="secondary">
          Unable to load broker status.
        </Text>
      </View>
    );
  }

  const statuses = query.data ?? [];

  return (
    <View style={{ gap: theme.spacing(3) }}>
      {statuses.map((s) => (
        <View key={s.broker} style={{ gap: theme.spacing(2) }}>
          <BrokerStatusBadge status={s} onPress={() => setConnecting(s.broker)} />
          {connecting === s.broker ? (
            <View style={{ paddingHorizontal: theme.spacing(1) }}>
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
