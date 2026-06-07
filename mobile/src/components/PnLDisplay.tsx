import React from 'react';

import { formatCurrency } from '../lib/format';
import { Text } from '../ui';
import type { AppTextProps } from '../ui';

export interface PnLDisplayProps {
  amount: number;
  pct: number;
  currency: string;
  compact?: boolean;
}

export function PnLDisplay({
  amount,
  pct,
  currency,
  compact = false,
}: PnLDisplayProps): React.ReactElement {
  // Defensive: callers may pass undefined/NaN (e.g. fields the backend omits),
  // so coerce to finite numbers rather than crashing on `.toFixed`.
  const safeAmount = Number.isFinite(amount) ? amount : 0;
  const safePct = Number.isFinite(pct) ? pct : 0;
  const positive = safeAmount > 0;
  const negative = safeAmount < 0;
  const sign = safeAmount >= 0 ? '+' : '';

  // gain → positive, loss → negative, flat → neutral.
  const color: AppTextProps['color'] = positive
    ? 'positive'
    : negative
      ? 'negative'
      : 'neutral';

  return (
    <Text
      variant={compact ? 'caption' : 'label'}
      weight="600"
      color={color}
      style={{ marginTop: compact ? 2 : 4, fontVariant: ['tabular-nums'] }}
    >
      {sign}
      {formatCurrency(safeAmount, currency)} ({sign}
      {safePct.toFixed(2)}%)
    </Text>
  );
}
