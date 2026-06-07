import React from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { useTheme } from '../theme';

export interface StaleDataMessageProps {
  level: 'suppressed';
}

export function StaleDataMessage(_props: StaleDataMessageProps): React.ReactElement {
  const theme = useTheme();
  return (
    <View
      style={[
        styles.banner,
        {
          backgroundColor: theme.colors.warningBg,
          borderColor: theme.colors.warningBorder,
        },
      ]}
      accessibilityRole="alert"
    >
      <Text style={[styles.title, { color: theme.colors.warning }]}>
        Recommendation suppressed
      </Text>
      <Text style={[styles.body, { color: theme.colors.textSecondary }]}>
        Data too old — analysis may not reflect current market conditions.
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  banner: {
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: 8,
    padding: 12,
    gap: 4,
  },
  title: {
    fontSize: 13,
    fontWeight: '700',
  },
  body: {
    fontSize: 13,
    lineHeight: 18,
  },
});
