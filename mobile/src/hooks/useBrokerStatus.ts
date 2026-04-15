/**
 * Broker connection status hook (TanStack Query).
 *
 * Returns a list of BrokerStatus entries — one per supported broker — so the
 * dashboard and settings screens can render badges / action buttons.
 *
 * TODO: wire to GET /api/auth/broker/connections once the backend endpoint is
 * added. Today `backend/app/api/broker_auth.py` only exposes `/{broker}/connect`
 * and `/{broker}/callback`; there is no list/status route yet. The existing
 * `mobile/src/components/BrokerConnect.tsx` also does not read connection
 * state. Until the backend lands, this hook returns a hardcoded stub marking
 * both brokers as disconnected so the UI can be built and validated.
 */

import { useQuery, UseQueryResult } from '@tanstack/react-query';

import { useAuthStore } from '../store/auth';

export type BrokerName = 'alpaca' | 'zerodha';
export type BrokerConnStatus = 'connected' | 'disconnected' | 'expired';
export type BrokerAction = 'synced' | 'relogin' | 'connect';

export interface BrokerStatus {
  broker: BrokerName;
  status: BrokerConnStatus;
  label: string;
  action: BrokerAction;
}

const BROKER_LABELS: Record<BrokerName, string> = {
  alpaca: 'Alpaca',
  zerodha: 'Zerodha',
};

/**
 * Backend connection row (shape expected once
 * GET /api/auth/broker/connections lands). `AUTH_EXPIRED` is emitted when the
 * broker access_token has expired and the user must re-run the OAuth flow
 * (e.g. Kite Connect tokens expire daily at 06:00 IST).
 */
export type BackendBrokerState = 'CONNECTED' | 'DISCONNECTED' | 'AUTH_EXPIRED';

export interface BackendBrokerConnection {
  broker: BrokerName;
  state: BackendBrokerState;
}

export function mapBackendToBrokerStatus(
  rows: readonly BackendBrokerConnection[],
): BrokerStatus[] {
  const byBroker = new Map<BrokerName, BackendBrokerState>();
  for (const r of rows) byBroker.set(r.broker, r.state);
  return (['alpaca', 'zerodha'] as const).map((broker): BrokerStatus => {
    const state = byBroker.get(broker) ?? 'DISCONNECTED';
    if (state === 'CONNECTED') {
      return { broker, status: 'connected', label: BROKER_LABELS[broker], action: 'synced' };
    }
    if (state === 'AUTH_EXPIRED') {
      return { broker, status: 'expired', label: BROKER_LABELS[broker], action: 'relogin' };
    }
    return { broker, status: 'disconnected', label: BROKER_LABELS[broker], action: 'connect' };
  });
}

function stubStatuses(): BrokerStatus[] {
  // TODO: replace with real backend call once
  // GET /api/auth/broker/connections is implemented.
  return (['alpaca', 'zerodha'] as const).map((broker) => ({
    broker,
    status: 'disconnected' as const,
    label: BROKER_LABELS[broker],
    action: 'connect' as const,
  }));
}

export function useBrokerStatus(): UseQueryResult<BrokerStatus[], Error> {
  const status = useAuthStore((s) => s.status);
  return useQuery({
    queryKey: ['broker', 'status'],
    queryFn: async (): Promise<BrokerStatus[]> => {
      // TODO: const raw = await apiGet<BackendConnection[]>('/api/auth/broker/connections');
      // return mapBackendToBrokerStatus(raw);
      return stubStatuses();
    },
    enabled: status === 'authenticated',
    staleTime: 30_000,
  });
}
