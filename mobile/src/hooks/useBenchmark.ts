/**
 * Benchmark data hooks (TanStack Query).
 *
 * Queries the FastAPI backend for cross-market benchmark returns.
 *
 * Expected contract (matches backend `BenchmarkReturn` schema from M4-23):
 *   interface BenchmarkReturn {
 *     symbol: string;
 *     currency: string;
 *     period_days: number;
 *     period_start: string;   // ISO date
 *     period_end: string;     // ISO date
 *     close_start: number;
 *     close_end: number;
 *     total_return: number;   // fraction, e.g. 0.0523 for +5.23%
 *     stale: boolean;
 *   }
 *
 * Endpoints (contract — wiring lands in a later job):
 *   GET  /api/benchmark?symbol={symbol}&period_days={n}
 *   POST /api/benchmark/blended
 *        body: { weights_by_venue: Record<string, number>;
 *                base_currency: string;
 *                period_days: number }
 */

import { useQuery, UseQueryResult } from '@tanstack/react-query';

import { apiGet, apiPost } from '../api/client';
import { useAuthStore } from '../store/auth';

export interface BenchmarkReturn {
  symbol: string;
  currency: string;
  period_days: number;
  period_start: string;
  period_end: string;
  close_start: number;
  close_end: number;
  total_return: number;
  stale: boolean;
}

export interface BlendedBenchmarkRequest {
  weights_by_venue: Record<string, number>;
  base_currency: string;
  period_days: number;
}

export interface BlendedBenchmarkReturn {
  base_currency: string;
  period_days: number;
  period_start: string;
  period_end: string;
  total_return: number;
  stale: boolean;
  components: BenchmarkReturn[];
  weights_by_venue: Record<string, number>;
}

export function useBenchmark(
  symbol: string,
  periodDays: number,
): UseQueryResult<BenchmarkReturn, Error> {
  const status = useAuthStore((s) => s.status);
  return useQuery({
    queryKey: ['benchmark', symbol, periodDays],
    queryFn: () =>
      apiGet<BenchmarkReturn>(
        `/api/benchmark?symbol=${encodeURIComponent(symbol)}&period_days=${periodDays}`,
      ),
    enabled: status === 'authenticated' && symbol.length > 0 && periodDays > 0,
    staleTime: 60_000,
  });
}

export function useBlendedBenchmark(
  request: BlendedBenchmarkRequest,
): UseQueryResult<BlendedBenchmarkReturn, Error> {
  const status = useAuthStore((s) => s.status);
  const { weights_by_venue, base_currency, period_days } = request;
  const weightsKey = Object.keys(weights_by_venue)
    .sort()
    .map((k) => `${k}:${weights_by_venue[k]}`)
    .join(',');
  return useQuery({
    queryKey: ['benchmark', 'blended', base_currency, period_days, weightsKey],
    queryFn: () =>
      apiPost<BlendedBenchmarkReturn, BlendedBenchmarkRequest>(
        '/api/benchmark/blended',
        request,
      ),
    enabled:
      status === 'authenticated' &&
      period_days > 0 &&
      base_currency.length > 0 &&
      Object.keys(weights_by_venue).length > 0,
    staleTime: 60_000,
  });
}
