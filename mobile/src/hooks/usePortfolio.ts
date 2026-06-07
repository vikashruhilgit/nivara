/**
 * Portfolio data hooks (TanStack Query).
 *
 * Queries the FastAPI backend:
 *   - GET /api/portfolio/summary   → PortfolioSummary
 *   - GET /api/portfolio/positions → PositionsList { positions, base_currency, as_of, is_stale }
 *
 * The positions endpoint returns an envelope; this hook unwraps it to the
 * positions array and normalises native/base fields so existing UI consumers
 * (HoldingRow, HoldingsList, PnLDisplay) keep working on the display keys
 * (`market_value`, `unrealized_pl`, `unrealized_pl_pct`) while new code can
 * read the canonical backend fields (`market_value_native`,
 * `market_value_base`, `fx_attribution`, etc.).
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

/**
 * Backend wire shape for GET /api/portfolio/summary (``PortfolioSummaryOut``).
 * Money values are Decimals serialised as JSON strings, and the backend does
 * NOT send a daily-change percentage — both are reconciled in normalizeSummary.
 */
interface PortfolioSummaryOut {
  base_currency: string;
  total_value: string;
  total_cost_basis: string;
  total_unrealized_pl: string;
  daily_pl: string;
  position_count: number;
  as_of: string;
  is_stale: boolean;
  confidence: string;
}

/** Coerce a string/number/undefined to a finite number, defaulting to 0. */
function toNumber(value: unknown): number {
  const n = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(n) ? n : 0;
}

/**
 * Map the backend summary onto the display shape the UI consumes. Coerces
 * string Decimals to numbers and derives ``day_change_pct`` (which the backend
 * does not return) from the prior value, guarding against division by zero for
 * an empty / cash-only portfolio.
 */
function normalizeSummary(raw: PortfolioSummaryOut): PortfolioSummary {
  const totalValue = toNumber(raw.total_value);
  const dayChange = toNumber(raw.daily_pl);
  const prior = totalValue - dayChange;
  const dayChangePct = prior !== 0 ? (dayChange / prior) * 100 : 0;
  return {
    total_value: totalValue,
    cash: 0, // not provided by the backend summary; unused by the UI
    positions_value: totalValue, // backend has no cash/positions split
    day_change: dayChange,
    day_change_pct: dayChangePct,
    currency: raw.base_currency,
  };
}

/**
 * FX attribution for cross-currency holdings. Mirrors backend
 * ``FxAttributionOut`` (snake_case, all numeric fields are Decimals serialised
 * as JSON numbers by FastAPI).
 */
export interface FxAttribution {
  stock_return_pct: number;
  fx_impact_pct: number;
  base_return_pct: number;
  note_text: string;
}

/**
 * Backend ``PositionOut`` wire shape. All money values are numbers (Decimals
 * serialised as JSON). Field names match the backend exactly (snake_case) so
 * we don't drift from the Pydantic schema.
 */
export interface PositionOut {
  instrument_id: string;
  symbol: string;
  exchange?: string | null;
  quantity: number;
  avg_cost: number;
  currency: string;
  market_value_native: number;
  unrealized_pl_native: number;
  base_currency: string;
  market_value_base: number;
  unrealized_pl_base: number;
  fx_rate: number;
  as_of: string;
  fx_attribution?: FxAttribution | null;
}

export interface PositionsList {
  positions: PositionOut[];
  base_currency: string;
  as_of: string;
  is_stale: boolean;
}

/**
 * Client-side view model for a position. Extends the backend ``PositionOut``
 * with derived display fields used by UI components:
 *
 * * ``market_value``        — native market value (same as ``market_value_native``).
 * * ``unrealized_pl``       — native unrealized P&L (same as ``unrealized_pl_native``).
 * * ``unrealized_pl_pct``   — derived from ``unrealized_pl_native / (quantity * avg_cost)``.
 * * ``current_price``       — not currently returned by the backend; left optional.
 */
export interface Position extends PositionOut {
  market_value: number;
  unrealized_pl: number;
  unrealized_pl_pct: number;
  current_price?: number;
}

function normalizePosition(p: PositionOut): Position {
  const costBasis = Number(p.quantity) * Number(p.avg_cost);
  const pl = Number(p.unrealized_pl_native);
  const pct = costBasis > 0 ? (pl / costBasis) * 100 : 0;
  return {
    ...p,
    market_value: Number(p.market_value_native),
    unrealized_pl: pl,
    unrealized_pl_pct: pct,
  };
}

export function usePortfolioSummary(): UseQueryResult<PortfolioSummary, Error> {
  const status = useAuthStore((s) => s.status);
  return useQuery({
    queryKey: ['portfolio', 'summary'],
    queryFn: () =>
      apiGet<PortfolioSummaryOut>('/api/portfolio/summary').then(normalizeSummary),
    enabled: status === 'authenticated',
    staleTime: 30_000,
  });
}

export function usePositions(): UseQueryResult<Position[], Error> {
  const status = useAuthStore((s) => s.status);
  return useQuery({
    queryKey: ['portfolio', 'positions'],
    queryFn: () =>
      apiGet<PositionsList>('/api/portfolio/positions').then((body) =>
        body.positions.map(normalizePosition),
      ),
    enabled: status === 'authenticated',
    staleTime: 30_000,
  });
}
