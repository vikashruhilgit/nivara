/**
 * Screen — page-level wrapper: themed background, a dot-texture layer behind
 * content, and safe-area handling. Optionally scrollable.
 *
 * The texture sits absolute-fill BEHIND content and never intercepts touches.
 */

import { ScrollView, StyleSheet, View } from 'react-native';
import type { StyleProp, ViewStyle } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { useTheme } from '../theme';
import { DotTexture } from './DotTexture';

type Edge = 'top' | 'bottom' | 'left' | 'right';

export interface ScreenProps {
  children?: React.ReactNode;
  /** Applied to the content container (the inner View / ScrollView content). */
  style?: StyleProp<ViewStyle>;
  scroll?: boolean;
  padded?: boolean;
  edges?: Edge[];
  contentContainerStyle?: StyleProp<ViewStyle>;
}

export function Screen({
  children,
  style,
  scroll = false,
  padded = false,
  edges = ['top'],
  contentContainerStyle,
}: ScreenProps): React.ReactElement {
  const theme = useTheme();
  const padding = padded ? { padding: theme.spacing(4) } : undefined;

  return (
    <View style={[styles.root, { backgroundColor: theme.colors.background }]}>
      <DotTexture />
      <SafeAreaView style={styles.safe} edges={edges}>
        {scroll ? (
          <ScrollView
            style={styles.flex}
            contentContainerStyle={[padding, contentContainerStyle, style]}
          >
            {children}
          </ScrollView>
        ) : (
          <View style={[styles.flex, padding, style]}>{children}</View>
        )}
      </SafeAreaView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1 },
  safe: { flex: 1 },
  flex: { flex: 1 },
});
