/**
 * UI primitive smoke + interaction tests. Everything renders under the real
 * <ThemeProvider> so useTheme() resolves.
 */

import { fireEvent, render, screen } from '@testing-library/react-native';
import React from 'react';

import { ThemeProvider } from '../theme';
import { Badge, Button, Card, Surface, Text } from '../ui';
import type { AppTextProps } from '../ui';

function wrap(node: React.ReactElement): React.ReactElement {
  return <ThemeProvider>{node}</ThemeProvider>;
}

describe('Surface', () => {
  it('renders children without throwing (auto/solid/glass)', () => {
    for (const variant of ['auto', 'solid', 'glass'] as const) {
      const { unmount } = render(
        wrap(
          <Surface variant={variant}>
            <Text>surface-{variant}</Text>
          </Surface>,
        ),
      );
      expect(screen.getByText(`surface-${variant}`)).toBeTruthy();
      unmount();
    }
  });
});

describe('Card', () => {
  it('renders and fires onPress', () => {
    const onPress = jest.fn();
    render(
      wrap(
        <Card onPress={onPress}>
          <Text>card-content</Text>
        </Card>,
      ),
    );
    expect(screen.getByText('card-content')).toBeTruthy();
    fireEvent.press(screen.getByText('card-content'));
    expect(onPress).toHaveBeenCalledTimes(1);
  });
});

describe('Text', () => {
  const variants: NonNullable<AppTextProps['variant']>[] = [
    'h1',
    'h2',
    'title',
    'body',
    'label',
    'caption',
  ];
  const colors: NonNullable<AppTextProps['color']>[] = [
    'primary',
    'secondary',
    'tertiary',
    'accent',
    'onAccent',
    'positive',
    'negative',
    'warning',
    'neutral',
  ];

  it('renders every variant', () => {
    for (const variant of variants) {
      const { unmount } = render(wrap(<Text variant={variant}>v-{variant}</Text>));
      expect(screen.getByText(`v-${variant}`)).toBeTruthy();
      unmount();
    }
  });

  it('renders every color', () => {
    for (const color of colors) {
      const { unmount } = render(wrap(<Text color={color}>c-{color}</Text>));
      expect(screen.getByText(`c-${color}`)).toBeTruthy();
      unmount();
    }
  });
});

describe('Button', () => {
  const variants = ['primary', 'secondary', 'ghost', 'danger'] as const;

  it('renders every variant', () => {
    for (const variant of variants) {
      const { unmount } = render(
        wrap(<Button title={`btn-${variant}`} variant={variant} />),
      );
      expect(screen.getByText(`btn-${variant}`)).toBeTruthy();
      unmount();
    }
  });

  it('fires onPress when enabled', () => {
    const onPress = jest.fn();
    render(wrap(<Button title="go" onPress={onPress} />));
    fireEvent.press(screen.getByText('go'));
    expect(onPress).toHaveBeenCalledTimes(1);
  });

  it('does not fire onPress when disabled', () => {
    const onPress = jest.fn();
    render(wrap(<Button title="nope" onPress={onPress} disabled />));
    fireEvent.press(screen.getByText('nope'));
    expect(onPress).not.toHaveBeenCalled();
  });

  it('shows a loading indicator and suppresses press', () => {
    const onPress = jest.fn();
    render(
      wrap(<Button title="loading-btn" onPress={onPress} loading accessibilityLabel="load" />),
    );
    // Title text is replaced by the ActivityIndicator while loading.
    expect(screen.queryByText('loading-btn')).toBeNull();
    fireEvent.press(screen.getByLabelText('load'));
    expect(onPress).not.toHaveBeenCalled();
  });
});

describe('Badge', () => {
  const tones = ['positive', 'negative', 'warning', 'neutral', 'accent'] as const;

  it('renders every tone', () => {
    for (const tone of tones) {
      const { unmount } = render(wrap(<Badge label={`tone-${tone}`} tone={tone} />));
      expect(screen.getByText(`tone-${tone}`)).toBeTruthy();
      unmount();
    }
  });
});

describe('theme-switch smoke', () => {
  it('mounts the primitive tree under the provider', () => {
    render(
      wrap(
        <Card>
          <Text variant="title">Investments</Text>
          <Badge label="Fresh" tone="positive" />
          <Button title="Connect" />
        </Card>,
      ),
    );
    expect(screen.getByText('Investments')).toBeTruthy();
    expect(screen.getByText('Fresh')).toBeTruthy();
    expect(screen.getByText('Connect')).toBeTruthy();
  });
});
