import { Tabs } from 'expo-router';
import { Text } from 'react-native';

/**
 * Tab icons are rendered as plain-text glyphs for the MVP shell so the app
 * builds without a vector-icon dependency. Swap these for `@expo/vector-icons`
 * once the icon set is chosen.
 */
function TabIcon({ label, color }: { label: string; color: string }): React.ReactElement {
  return <Text style={{ color, fontSize: 18 }}>{label}</Text>;
}

export default function TabsLayout(): React.ReactElement {
  return (
    <Tabs
      screenOptions={{
        tabBarActiveTintColor: '#1f6feb',
        tabBarInactiveTintColor: '#57606a',
        headerShown: true,
      }}
    >
      <Tabs.Screen
        name="portfolio"
        options={{
          title: 'Portfolio',
          tabBarIcon: ({ color }) => <TabIcon label="📊" color={color} />,
        }}
      />
      <Tabs.Screen
        name="insights"
        options={{
          title: 'Insights',
          tabBarIcon: ({ color }) => <TabIcon label="💡" color={color} />,
        }}
      />
      <Tabs.Screen
        name="settings"
        options={{
          title: 'Settings',
          tabBarIcon: ({ color }) => <TabIcon label="⚙" color={color} />,
        }}
      />
    </Tabs>
  );
}
