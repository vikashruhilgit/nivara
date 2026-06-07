/**
 * Button — themed pressable. Variants: primary (accent-filled),
 * secondary (surfaceAlt + border), ghost (transparent + accent text),
 * danger (negative-filled). Supports loading + disabled states.
 *
 * Hit target is >= 44px tall for a11y.
 */

import { ActivityIndicator, Pressable, StyleSheet, View } from 'react-native';
import type { StyleProp, TextStyle, ViewStyle } from 'react-native';

import { useTheme } from '../theme';
import type { Theme } from '../theme';
import { Text } from './Text';

export interface ButtonProps {
  title?: string;
  children?: React.ReactNode;
  onPress?: () => void;
  disabled?: boolean;
  loading?: boolean;
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger';
  style?: StyleProp<ViewStyle>;
  accessibilityLabel?: string;
}

interface VariantStyle {
  container: ViewStyle;
  textColor: string;
}

function variantStyle(
  theme: Theme,
  variant: NonNullable<ButtonProps['variant']>,
): VariantStyle {
  switch (variant) {
    case 'primary':
      return {
        container: { backgroundColor: theme.colors.accent },
        textColor: theme.colors.textOnAccent,
      };
    case 'secondary':
      return {
        container: {
          backgroundColor: theme.colors.surfaceAlt,
          borderWidth: StyleSheet.hairlineWidth,
          borderColor: theme.colors.border,
        },
        textColor: theme.colors.textPrimary,
      };
    case 'ghost':
      return {
        container: { backgroundColor: 'transparent' },
        textColor: theme.colors.accent,
      };
    case 'danger':
      return {
        container: { backgroundColor: theme.colors.negative },
        textColor: theme.colors.textOnAccent,
      };
  }
}

export function Button({
  title,
  children,
  onPress,
  disabled = false,
  loading = false,
  variant = 'primary',
  style,
  accessibilityLabel,
}: ButtonProps): React.ReactElement {
  const theme = useTheme();
  const vs = variantStyle(theme, variant);
  const isDisabled = disabled || loading;

  const base: ViewStyle = {
    minHeight: 48,
    paddingVertical: theme.spacing(3),
    paddingHorizontal: theme.spacing(4),
    borderRadius: theme.radii.md,
    alignItems: 'center',
    justifyContent: 'center',
  };

  const labelStyle: TextStyle = { textAlign: 'center' };

  return (
    <Pressable
      onPress={onPress}
      disabled={isDisabled}
      accessibilityRole="button"
      accessibilityState={{ disabled: isDisabled, busy: loading }}
      accessibilityLabel={accessibilityLabel ?? title}
      style={({ pressed }) => [
        base,
        vs.container,
        isDisabled && styles.disabled,
        pressed && !isDisabled && styles.pressed,
        style,
      ]}
    >
      {loading ? (
        <ActivityIndicator color={vs.textColor} />
      ) : children !== undefined ? (
        <View>{children}</View>
      ) : (
        <Text variant="label" style={[labelStyle, { color: vs.textColor }]}>
          {title}
        </Text>
      )}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  disabled: { opacity: 0.5 },
  pressed: { opacity: 0.8 },
});
