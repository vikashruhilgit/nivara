/**
 * Risk meter data hooks (TanStack Query).
 *
 * Queries the FastAPI backend:
 *   - GET /api/portfolio/risk-meter            -> RiskMeter
 *   - GET /api/portfolio/risk-meter/drilldown  -> RiskMeterDrilldown
 */

import { useQuery, UseQueryResult } from '@tanstack/react-query';

import { apiGet } from '../api/client';
import { useAuthStore } from '../store/auth';

export type RiskColor = 'green' | 'yellow' | 'red';
export type RiskStaleness = 'fresh' | 'stale' | 'very_stale';

export interface RiskMeter {
  overall_score: number;
  color: RiskColor;
  staleness: RiskStaleness;
  stale_reason: string | null;
}

export interface RiskComponent {
  name: string;
  score: number;
  weight: number;
  detail: Record<string, unknown> | null;
}

export interface RiskMeterDrilldown extends RiskMeter {
  components: RiskComponent[];
}

export function useRiskMeter(): UseQueryResult<RiskMeter, Error> {
  const status = useAuthStore((s) => s.status);
  return useQuery({
    queryKey: ['portfolio', 'risk-meter'],
    queryFn: () => apiGet<RiskMeter>('/api/portfolio/risk-meter'),
    enabled: status === 'authenticated',
    staleTime: 30_000,
  });
}

export function useRiskMeterDrilldown(): UseQueryResult<RiskMeterDrilldown, Error> {
  const status = useAuthStore((s) => s.status);
  return useQuery({
    queryKey: ['portfolio', 'risk-meter', 'drilldown'],
    queryFn: () => apiGet<RiskMeterDrilldown>('/api/portfolio/risk-meter/drilldown'),
    enabled: status === 'authenticated',
    staleTime: 30_000,
  });
}
