/**
 * UI primitive library barrel.
 *
 * Downstream usage:
 *   import { Surface, Screen, Card, Text, Button, Badge, DotTexture } from '../ui';
 *   // (from app/: '../../src/ui')
 */

export { Surface } from './Surface';
export type { SurfaceProps } from './Surface';

export { Screen } from './Screen';
export type { ScreenProps } from './Screen';

export { DotTexture } from './DotTexture';

export { Card } from './Card';
export type { CardProps } from './Card';

export { Text } from './Text';
export type { AppTextProps } from './Text';

export { Button } from './Button';
export type { ButtonProps } from './Button';

export { Badge } from './Badge';
export type { BadgeProps } from './Badge';
