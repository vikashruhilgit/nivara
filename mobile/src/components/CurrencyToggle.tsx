/**
 * CurrencyToggle — segmented INR/USD base-currency switch.
 */

import { Pressable, StyleSheet, Text, View } from 'react-native';

export type BaseCurrency = 'INR' | 'USD';

const OPTIONS: BaseCurrency[] = ['USD', 'INR'];

export function CurrencyToggle({
  value,
  onChange,
}: {
  value: BaseCurrency;
  onChange: (v: BaseCurrency) => void;
}): React.ReactElement {
  return (
    <View style={styles.row}>
      {OPTIONS.map((opt) => {
        const selected = opt === value;
        return (
          <Pressable
            key={opt}
            accessibilityRole="button"
            accessibilityState={{ selected }}
            onPress={() => onChange(opt)}
            style={({ pressed }) => [
              styles.segment,
              selected && styles.segmentSelected,
              pressed && !selected && styles.segmentPressed,
            ]}
          >
            <Text style={[styles.label, selected && styles.labelSelected]}>{opt}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    borderWidth: 1,
    borderColor: '#d0d7de',
    borderRadius: 999,
    padding: 3,
    alignSelf: 'flex-start',
    backgroundColor: '#fff',
  },
  segment: {
    paddingVertical: 8,
    paddingHorizontal: 18,
    borderRadius: 999,
  },
  segmentSelected: {
    backgroundColor: '#0969da',
  },
  segmentPressed: {
    opacity: 0.6,
  },
  label: {
    fontSize: 14,
    fontWeight: '600',
    color: '#57606a',
  },
  labelSelected: {
    color: '#fff',
  },
});
