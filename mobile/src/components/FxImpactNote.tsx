import React from 'react';

import { Text } from '../ui';

/**
 * FX impact attribution for a cross-currency holding.
 *
 * Shape matches backend `FxAttribution` schema. The backend pre-formats
 * `note_text` (e.g., "AAPL +8% USD, INR weakened 3%, your INR return: +11.2%"),
 * so this component simply renders it in a muted caption style underneath the
 * holding's cross-currency placeholder row.
 */
export interface FxAttribution {
  stock_return_pct: number;
  fx_impact_pct: number;
  base_return_pct: number;
  note_text: string;
}

export interface FxImpactNoteProps {
  attribution: FxAttribution;
}

export function FxImpactNote({
  attribution,
}: FxImpactNoteProps): React.ReactElement {
  return (
    <Text
      variant="caption"
      color="tertiary"
      style={{ marginTop: 2, fontStyle: 'italic' }}
      accessibilityLabel={`FX impact: ${attribution.note_text}`}
    >
      {attribution.note_text}
    </Text>
  );
}
