/**
 * Recommendations data hook (TanStack Query).
 *
 * Queries the FastAPI backend:
 *   - GET /api/recommendations -> Recommendation[]
 *
 * The backend returns a flexible list of recommendation payloads. Each item
 * broadly matches the RecommendationResponse schema from
 * /api/recommendations/generate, plus identifying fields (instrument_id,
 * symbol). All fields except `computed_at` are treated as optional so the UI
 * can render gracefully on partial data.
 */

import { useQuery, UseQueryResult } from '@tanstack/react-query';

import { apiGet } from '../api/client';
import { useAuthStore } from '../store/auth';

export type RecommendationAction =
  | 'strong_buy'
  | 'buy'
  | 'hold'
  | 'sell'
  | 'strong_sell';

export interface EngineScores {
  technical?: number | null;
  fundamental?: number | null;
  sentiment?: number | null;
  risk?: number | null;
}

export interface Recommendation {
  computed_at: string;
  instrument_id?: string;
  symbol?: string;
  status?: 'ok' | 'stale';
  action?: RecommendationAction | null;
  confidence?: number | null;
  composite_score?: number | null;
  engine_scores?: EngineScores | null;
  rationale?: string | null;
  expires_at?: string | null;
  reason?: string | null;
  explainer_used?: string | null;
  ai_blended?: boolean;
  staleness?: 'fresh' | 'aging' | 'stale' | 'suppressed';
}

export function useRecommendations(): UseQueryResult<Recommendation[], Error> {
  const status = useAuthStore((s) => s.status);
  return useQuery({
    queryKey: ['recommendations'],
    queryFn: () => apiGet<Recommendation[]>('/api/recommendations'),
    enabled: status === 'authenticated',
    staleTime: 60_000,
  });
}
