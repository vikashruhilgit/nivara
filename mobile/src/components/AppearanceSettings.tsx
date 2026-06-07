/**
 * AppearanceSettings — live theme control panel bound to useThemeStore.
 *
 * Three segmented groups: Mode (system/light/dark), Surface (glass/solid),
 * and Accent (indigo/emerald/graphite). Selecting any option updates the
 * whole app live (the store drives ThemeProvider) and persists automatically.
 *
 * All colors come from theme tokens — no raw hex. Each option is a >=44px
 * touch target with accessibilityRole='button' and accessibilityState.selected.
 */

import { Pressable, StyleSheet, View } from 'react-native';
import type { ViewStyle } from 'react-native';

import { useTheme, useThemeStore } from '../theme';
import type { AccentName, SurfaceStyle, ThemeMode } from '../theme';
import { Text } from '../ui';

interface Option<T extends string> {
  value: T;
  label: string;
}

const MODE_OPTIONS: Option<ThemeMode>[] = [
  { value: 'system', label: 'System' },
  { value: 'light', label: 'Light' },
  { value: 'dark', label: 'Dark' },
];

const SURFACE_OPTIONS: Option<SurfaceStyle>[] = [
  { value: 'glass', label: 'Glass' },
  { value: 'solid', label: 'Solid' },
];

const ACCENT_OPTIONS: Option<AccentName>[] = [
  { value: 'indigo', label: 'Indigo' },
  { value: 'emerald', label: 'Emerald' },
  { value: 'graphite', label: 'Graphite' },
];

function SegmentedControl<T extends string>({
  label,
  options,
  selected,
  onSelect,
}: {
  label: string;
  options: Option<T>[];
  selected: T;
  onSelect: (value: T) => void;
}): React.ReactElement {
  const theme = useTheme();
  const rowStyle: ViewStyle = {
    flexDirection: 'row',
    gap: theme.spacing(2),
    flexWrap: 'wrap',
  };

  return (
    <View style={{ gap: theme.spacing(2) }}>
      <Text variant="label" color="secondary">
        {label}
      </Text>
      <View style={rowStyle}>
        {options.map((opt) => {
          const isSelected = opt.value === selected;
          const segmentStyle: ViewStyle = {
            minHeight: 44,
            minWidth: 44,
            paddingVertical: theme.spacing(2),
            paddingHorizontal: theme.spacing(4),
            borderRadius: theme.radii.pill,
            borderWidth: StyleSheet.hairlineWidth,
            alignItems: 'center',
            justifyContent: 'center',
            backgroundColor: isSelected
              ? theme.colors.accentMuted
              : theme.colors.surfaceAlt,
            borderColor: isSelected ? theme.colors.accent : theme.colors.border,
          };
          return (
            <Pressable
              key={opt.value}
              accessibilityRole="button"
              accessibilityLabel={`${label}: ${opt.label}`}
              accessibilityState={{ selected: isSelected }}
              onPress={() => onSelect(opt.value)}
              style={({ pressed }) => [
                segmentStyle,
                pressed && styles.pressed,
              ]}
            >
              <Text
                variant="label"
                color={isSelected ? 'accent' : 'secondary'}
              >
                {opt.label}
              </Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

export function AppearanceSettings(): React.ReactElement {
  const theme = useTheme();

  const mode = useThemeStore((s) => s.mode);
  const surface = useThemeStore((s) => s.surface);
  const accent = useThemeStore((s) => s.accent);
  const setMode = useThemeStore((s) => s.setMode);
  const setSurface = useThemeStore((s) => s.setSurface);
  const setAccent = useThemeStore((s) => s.setAccent);

  return (
    <View style={{ gap: theme.spacing(4) }}>
      <SegmentedControl<ThemeMode>
        label="Mode"
        options={MODE_OPTIONS}
        selected={mode}
        onSelect={setMode}
      />
      <SegmentedControl<SurfaceStyle>
        label="Surface"
        options={SURFACE_OPTIONS}
        selected={surface}
        onSelect={setSurface}
      />
      <SegmentedControl<AccentName>
        label="Accent"
        options={ACCENT_OPTIONS}
        selected={accent}
        onSelect={setAccent}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  pressed: { opacity: 0.7 },
});
