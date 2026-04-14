/**
 * Portfolio data hooks (TanStack Query).
 *
 * Queries the FastAPI backend:
 *   - GET /api/portfolio/summary   → PortfolioSummary
 *   - GET /api/portfolio/positions → Position[]
 *
 * These endpoints are added by the portfolio service milestone. Until they
 * exist, the hooks surface errors through TanStack Query's standard error
 * state and the UI renders an "Unavailable" empty state.
 */

import { useQuery, UseQueryResult } from '@tanstack/react-query';

import { apiGet } from '../api/client';
import { useAuthStore } from '../store/auth';

export interface PortfolioSummary {
  total_value: number;
  cash: number;
  positions_value: number;
  day_change: number;
  day_change_pct: number;
  currency: string;
}

export interface Position {
  instrument_id: string;
  symbol: string;
  quantity: number;
  avg_cost: number;
  current_price: number;
  market_value: number;
  unrealized_pl: number;
  unrealized_pl_pct: number;
  currency: string;
}

export function usePortfolioSummary(): UseQueryResult<PortfolioSummary, Error> {
  const status = useAuthStore((s) => s.status);
  return useQuery({
    queryKey: ['portfolio', 'summary'],
    queryFn: () => apiGet<PortfolioSummary>('/api/portfolio/summary'),
    enabled: status === 'authenticated',
    staleTime: 30_000,
  });
}

export function usePositions(): UseQueryResult<Position[], Error> {
  const status = useAuthStore((s) => s.status);
  return useQuery({
    queryKey: ['portfolio', 'positions'],
    queryFn: () => apiGet<Position[]>('/api/portfolio/positions'),
    enabled: status === 'authenticated',
    staleTime: 30_000,
  });
}
