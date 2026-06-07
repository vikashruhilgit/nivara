/**
 * Text — themed text primitive. Maps `variant` → theme.typography and
 * `color` → theme.colors. Forwards all remaining RN Text props + style.
 */

import { Text as RNText } from 'react-native';
import type { TextProps as RNTextProps, TextStyle } from 'react-native';

import { useTheme } from '../theme';
import type { Theme } from '../theme';

export interface AppTextProps extends RNTextProps {
  variant?: 'h1' | 'h2' | 'title' | 'body' | 'label' | 'caption';
  color?:
    | 'primary'
    | 'secondary'
    | 'tertiary'
    | 'accent'
    | 'onAccent'
    | 'positive'
    | 'negative'
    | 'warning'
    | 'neutral';
  weight?: '400' | '500' | '600' | '700';
}

function colorFor(theme: Theme, color: NonNullable<AppTextProps['color']>): string {
  switch (color) {
    case 'primary':
      return theme.colors.textPrimary;
    case 'secondary':
      return theme.colors.textSecondary;
    case 'tertiary':
      return theme.colors.textTertiary;
    case 'accent':
      return theme.colors.accent;
    case 'onAccent':
      return theme.colors.textOnAccent;
    case 'positive':
      return theme.colors.positive;
    case 'negative':
      return theme.colors.negative;
    case 'warning':
      return theme.colors.warning;
    case 'neutral':
      return theme.colors.neutral;
  }
}

export function Text({
  variant = 'body',
  color = 'primary',
  weight,
  style,
  ...rest
}: AppTextProps): React.ReactElement {
  const theme = useTheme();
  const typo = theme.typography[variant];

  const base: TextStyle = {
    fontSize: typo.fontSize,
    fontWeight: weight ?? typo.fontWeight,
    lineHeight: typo.lineHeight,
    color: colorFor(theme, color),
  };

  return <RNText style={[base, style]} {...rest} />;
}
