/**
 * Badge — small status pill. Maps `tone` to the matching status fg/bg/border
 * tokens (or accent). Pill radius.
 */

import { StyleSheet, View } from 'react-native';
import type { StyleProp, ViewStyle } from 'react-native';

import { useTheme } from '../theme';
import type { Theme } from '../theme';
import { Text } from './Text';

export interface BadgeProps {
  label: string;
  tone?: 'positive' | 'negative' | 'warning' | 'neutral' | 'accent';
  style?: StyleProp<ViewStyle>;
}

interface ToneStyle {
  fg: string;
  bg: string;
  border: string;
}

function toneStyle(theme: Theme, tone: NonNullable<BadgeProps['tone']>): ToneStyle {
  switch (tone) {
    case 'positive':
      return {
        fg: theme.colors.positive,
        bg: theme.colors.positiveBg,
        border: theme.colors.positiveBorder,
      };
    case 'negative':
      return {
        fg: theme.colors.negative,
        bg: theme.colors.negativeBg,
        border: theme.colors.negativeBorder,
      };
    case 'warning':
      return {
        fg: theme.colors.warning,
        bg: theme.colors.warningBg,
        border: theme.colors.warningBorder,
      };
    case 'neutral':
      return {
        fg: theme.colors.neutral,
        bg: theme.colors.neutralBg,
        border: theme.colors.neutralBorder,
      };
    case 'accent':
      return {
        fg: theme.colors.accent,
        bg: theme.colors.accentMuted,
        border: theme.colors.accent,
      };
  }
}

export function Badge({
  label,
  tone = 'neutral',
  style,
}: BadgeProps): React.ReactElement {
  const theme = useTheme();
  const ts = toneStyle(theme, tone);

  return (
    <View
      style={[
        styles.pill,
        {
          backgroundColor: ts.bg,
          borderColor: ts.border,
          borderRadius: theme.radii.pill,
          paddingHorizontal: theme.spacing(2),
          paddingVertical: theme.spacing(1),
        },
        style,
      ]}
    >
      <Text variant="caption" weight="700" style={{ color: ts.fg }}>
        {label}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  pill: {
    borderWidth: StyleSheet.hairlineWidth,
    alignSelf: 'flex-start',
  },
});
