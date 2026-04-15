import { StyleSheet, Text, View } from 'react-native';

import { InsightFeed } from '../../src/components/InsightFeed';

export default function InsightsScreen(): React.ReactElement {
  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.title}>Insights</Text>
      </View>
      <InsightFeed />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  header: { paddingHorizontal: 16, paddingTop: 16, paddingBottom: 8 },
  title: { fontSize: 24, fontWeight: '700' },
});
