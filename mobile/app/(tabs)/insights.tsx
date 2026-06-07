import { View } from 'react-native';

import { InsightFeed } from '../../src/components/InsightFeed';
import { useTheme } from '../../src/theme';
import { Screen, Text } from '../../src/ui';

export default function InsightsScreen(): React.ReactElement {
  const theme = useTheme();

  return (
    <Screen>
      <View style={{ paddingHorizontal: theme.spacing(4), paddingTop: theme.spacing(2) }}>
        <Text variant="h1">Insights</Text>
        <Text variant="body" color="secondary" style={{ marginTop: theme.spacing(1) }}>
          AI-generated signals across your watchlist.
        </Text>
      </View>
      <InsightFeed />
    </Screen>
  );
}
