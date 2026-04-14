import { ScrollView, StyleSheet, Text, View } from 'react-native';

export default function InsightsScreen(): React.ReactElement {
  return (
    <ScrollView contentContainerStyle={styles.container}>
      <Text style={styles.title}>Insights</Text>
      <Text style={styles.sub}>
        AI-generated recommendations will appear here. This milestone delivers the app shell; the
        insights feed is wired up in a later milestone.
      </Text>
      <View style={styles.card}>
        <Text style={styles.cardTitle}>Coming soon</Text>
        <Text style={styles.sub}>
          Portfolio recommendations, market alerts, and per-position signals.
        </Text>
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { padding: 24, gap: 16 },
  title: { fontSize: 24, fontWeight: '700' },
  sub: { fontSize: 14, color: '#57606a' },
  card: {
    padding: 16,
    borderRadius: 8,
    backgroundColor: '#f6f8fa',
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: '#d0d7de',
    gap: 8,
  },
  cardTitle: { fontSize: 16, fontWeight: '600' },
});
