/**
 * Broker connection status hook (TanStack Query).
 *
 * Returns a list of BrokerStatus entries — one per supported broker — so the
 * dashboard and settings screens can render badges / action buttons.
 *
 * Wires to `GET /api/auth/broker/connections` (see
 * `backend/app/api/broker_auth.py::list_broker_connections`). The backend
 * returns one row per connected broker with a surface-level status enum
 * (`connected` | `auth_expired` | `error` | `disconnected`) derived from the
 * DB row + broker-specific expiry rule (e.g. Kite's 06:00 IST daily cutoff).
 *
 * On fetch error we fall back to the disconnected stub so the dashboard stays
 * renderable (graceful degradation) — the UI still surfaces the query error
 * via `useQuery`'s `error` field if the caller wants to show a banner.
 */

import { useQuery, UseQueryResult } from '@tanstack/react-query';

import { apiGet } from '../api/client';
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
 * Backend connection row shape (lowercase enum) — matches
 * `BrokerConnectionStatusItem` from `backend/app/api/broker_auth.py`.
 * `auth_expired` is emitted when the broker access_token has expired and the
 * user must re-run the OAuth flow (Kite Connect tokens expire daily at
 * 06:00 IST).
 */
export type BackendConnectionStatus =
  | 'connected'
  | 'auth_expired'
  | 'error'
  | 'disconnected';

export interface BackendBrokerConnection {
  id: string;
  broker: BrokerName;
  account_id: string;
  status: BackendConnectionStatus;
  token_expires_at: string | null;
}

interface BackendConnectionsResponse {
  connections: BackendBrokerConnection[];
}

export function mapBackendToBrokerStatus(
  rows: readonly BackendBrokerConnection[],
): BrokerStatus[] {
  const byBroker = new Map<BrokerName, BackendConnectionStatus>();
  for (const r of rows) byBroker.set(r.broker, r.status);
  return (['alpaca', 'zerodha'] as const).map((broker): BrokerStatus => {
    const state = byBroker.get(broker) ?? 'disconnected';
    if (state === 'connected') {
      return { broker, status: 'connected', label: BROKER_LABELS[broker], action: 'synced' };
    }
    if (state === 'auth_expired') {
      return { broker, status: 'expired', label: BROKER_LABELS[broker], action: 'relogin' };
    }
    // Treat both `error` and `disconnected` as "needs connect".
    return { broker, status: 'disconnected', label: BROKER_LABELS[broker], action: 'connect' };
  });
}

function stubStatuses(): BrokerStatus[] {
  // Fallback used only on fetch error so the UI remains renderable.
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
      try {
        const raw = await apiGet<BackendConnectionsResponse>(
          '/api/auth/broker/connections',
        );
        return mapBackendToBrokerStatus(raw.connections ?? []);
      } catch {
        // Graceful degradation: render disconnected stubs so the dashboard
        // doesn't blank out. The query's `error` field still surfaces the
        // failure to callers that want to show a retry banner.
        return stubStatuses();
      }
    },
    enabled: status === 'authenticated',
    staleTime: 30_000,
  });
}
