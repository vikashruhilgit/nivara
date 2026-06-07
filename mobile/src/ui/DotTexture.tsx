/**
 * DotTexture — subtle SVG dot-grid background layer.
 *
 * Absolute-fill, pointerEvents="none", driven entirely by theme.texture tokens.
 * Must stay subtle enough to never reduce text contrast (WCAG AA).
 */

import { StyleSheet } from 'react-native';
import type { StyleProp, ViewStyle } from 'react-native';
import Svg, { Circle, Defs, Pattern, Rect } from 'react-native-svg';

import { useTheme } from '../theme';

export function DotTexture(props?: {
  style?: StyleProp<ViewStyle>;
}): React.ReactElement {
  const theme = useTheme();
  const { dotColor, dotRadius, spacing, opacity } = theme.texture;

  return (
    <Svg
      style={[StyleSheet.absoluteFill, props?.style]}
      pointerEvents="none"
      width="100%"
      height="100%"
      opacity={opacity}
    >
      <Defs>
        <Pattern
          id="dotGrid"
          x="0"
          y="0"
          width={spacing}
          height={spacing}
          patternUnits="userSpaceOnUse"
        >
          <Circle
            cx={spacing / 2}
            cy={spacing / 2}
            r={dotRadius}
            fill={dotColor}
          />
        </Pattern>
      </Defs>
      <Rect x="0" y="0" width="100%" height="100%" fill="url(#dotGrid)" />
    </Svg>
  );
}
