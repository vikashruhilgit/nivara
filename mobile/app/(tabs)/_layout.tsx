import { Ionicons } from '@expo/vector-icons';
import { BlurView } from 'expo-blur';
import { Tabs } from 'expo-router';
import { Platform, StyleSheet, View } from 'react-native';

import { useTheme } from '../../src/theme';

type IoniconName = React.ComponentProps<typeof Ionicons>['name'];

/**
 * Glass tab-bar background: a real BlurView on iOS when the theme uses glass,
 * otherwise a themed solid fill. Driven entirely by theme tokens.
 */
function TabBarBackground(): React.ReactElement {
  const theme = useTheme();
  const useGlass = theme.surfaceStyle === 'glass' && Platform.OS === 'ios';

  if (useGlass) {
    return (
      <View style={StyleSheet.absoluteFill}>
        <BlurView
          intensity={theme.glass.blurIntensity}
          tint={theme.glass.blurTint}
          style={StyleSheet.absoluteFill}
        />
        <View
          style={[
            StyleSheet.absoluteFill,
            { backgroundColor: theme.colors.surfaceGlassTint },
          ]}
        />
      </View>
    );
  }

  return (
    <View
      style={[
        StyleSheet.absoluteFill,
        { backgroundColor: theme.colors.backgroundElevated },
      ]}
    />
  );
}

export default function TabsLayout(): React.ReactElement {
  const theme = useTheme();
  const useGlass = theme.surfaceStyle === 'glass' && Platform.OS === 'ios';

  return (
    <Tabs
      screenOptions={{
        tabBarActiveTintColor: theme.colors.accent,
        tabBarInactiveTintColor: theme.colors.textSecondary,
        headerShown: true,
        headerStyle: { backgroundColor: theme.colors.backgroundElevated },
        headerTitleStyle: { color: theme.colors.textPrimary },
        headerTintColor: theme.colors.textPrimary,
        headerShadowVisible: false,
        tabBarStyle: {
          backgroundColor: useGlass ? 'transparent' : theme.colors.backgroundElevated,
          borderTopColor: theme.colors.border,
          borderTopWidth: StyleSheet.hairlineWidth,
          ...(useGlass ? { position: 'absolute' } : null),
        },
        tabBarBackground: () => <TabBarBackground />,
      }}
    >
      <Tabs.Screen
        name="portfolio"
        options={{
          title: 'Portfolio',
          tabBarIcon: ({ color, size }) => (
            <Ionicons name={'pie-chart' as IoniconName} color={color} size={size} />
          ),
        }}
      />
      <Tabs.Screen
        name="insights"
        options={{
          title: 'Insights',
          tabBarIcon: ({ color, size }) => (
            <Ionicons name={'bulb' as IoniconName} color={color} size={size} />
          ),
        }}
      />
      <Tabs.Screen
        name="settings"
        options={{
          title: 'Settings',
          tabBarIcon: ({ color, size }) => (
            <Ionicons name={'settings' as IoniconName} color={color} size={size} />
          ),
        }}
      />
    </Tabs>
  );
}
