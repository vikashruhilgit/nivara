/**
 * CurrencyToggle — segmented INR/USD base-currency switch.
 *
 * Token-driven styling: selected = accentMuted bg / accent text / accent border,
 * unselected = surfaceAlt / textSecondary / border. No raw hex.
 */

import { Pressable, StyleSheet, View } from 'react-native';
import type { ViewStyle } from 'react-native';

import { useTheme } from '../theme';
import { Text } from '../ui';

export type BaseCurrency = 'INR' | 'USD';

const OPTIONS: BaseCurrency[] = ['USD', 'INR'];

export function CurrencyToggle({
  value,
  onChange,
}: {
  value: BaseCurrency;
  onChange: (v: BaseCurrency) => void;
}): React.ReactElement {
  const theme = useTheme();

  const rowStyle: ViewStyle = {
    flexDirection: 'row',
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.colors.border,
    borderRadius: theme.radii.pill,
    padding: theme.spacing(1),
    alignSelf: 'flex-start',
    backgroundColor: theme.colors.surfaceAlt,
    gap: theme.spacing(1),
  };

  return (
    <View style={rowStyle}>
      {OPTIONS.map((opt) => {
        const selected = opt === value;
        const segmentStyle: ViewStyle = {
          minHeight: 44,
          minWidth: 44,
          paddingVertical: theme.spacing(2),
          paddingHorizontal: theme.spacing(4),
          borderRadius: theme.radii.pill,
          borderWidth: StyleSheet.hairlineWidth,
          alignItems: 'center',
          justifyContent: 'center',
          backgroundColor: selected ? theme.colors.accentMuted : 'transparent',
          borderColor: selected ? theme.colors.accent : 'transparent',
        };
        return (
          <Pressable
            key={opt}
            accessibilityRole="button"
            accessibilityLabel={`Base currency ${opt}`}
            accessibilityState={{ selected }}
            onPress={() => onChange(opt)}
            style={({ pressed }) => [
              segmentStyle,
              pressed && !selected && styles.pressed,
            ]}
          >
            <Text variant="label" color={selected ? 'accent' : 'secondary'}>
              {opt}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  pressed: { opacity: 0.6 },
});
