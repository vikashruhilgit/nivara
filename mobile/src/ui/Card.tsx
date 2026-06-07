/**
 * Card — thin preset over Surface (auto variant, sm elevation, lg radius,
 * default inner padding). Optionally pressable.
 */

import { Pressable, StyleSheet, View } from 'react-native';
import type { StyleProp, ViewStyle } from 'react-native';

import { useTheme } from '../theme';
import { Surface } from './Surface';

export interface CardProps {
  children?: React.ReactNode;
  style?: StyleProp<ViewStyle>;
  onPress?: () => void;
  context?: 'static' | 'list';
  padded?: boolean;
}

export function Card({
  children,
  style,
  onPress,
  context = 'static',
  padded = true,
}: CardProps): React.ReactElement {
  const theme = useTheme();
  const padStyle: ViewStyle | undefined = padded
    ? { padding: theme.spacing(4) }
    : undefined;

  const inner = (
    <Surface variant="auto" elevation="sm" radius="lg" context={context} style={style}>
      <View style={padStyle}>{children}</View>
    </Surface>
  );

  if (onPress) {
    return (
      <Pressable
        onPress={onPress}
        style={({ pressed }) => (pressed ? styles.pressed : undefined)}
      >
        {inner}
      </Pressable>
    );
  }

  return inner;
}

const styles = StyleSheet.create({
  pressed: { opacity: 0.85 },
});
