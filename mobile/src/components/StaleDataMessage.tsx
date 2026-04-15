import React from 'react';
import { StyleSheet, Text, View } from 'react-native';

export interface StaleDataMessageProps {
  level: 'suppressed';
}

export function StaleDataMessage(_props: StaleDataMessageProps): React.ReactElement {
  return (
    <View style={styles.banner} accessibilityRole="alert">
      <Text style={styles.title}>Recommendation suppressed</Text>
      <Text style={styles.body}>
        Data too old — analysis may not reflect current market conditions.
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  banner: {
    backgroundColor: '#ffebe9',
    borderColor: '#cf222e',
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: 8,
    padding: 12,
    gap: 4,
  },
  title: {
    fontSize: 13,
    fontWeight: '700',
    color: '#cf222e',
  },
  body: {
    fontSize: 13,
    color: '#1f2328',
    lineHeight: 18,
  },
});
