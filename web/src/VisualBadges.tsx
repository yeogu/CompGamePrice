import {
  Gamepad2,
  Laptop,
  Monitor,
  ShoppingBag,
  Smartphone,
  Tablet,
  Terminal,
  type LucideIcon,
} from 'lucide-react'

type BadgeProps = {
  compact?: boolean
  label?: string
}

type PlatformBadgeProps = BadgeProps & {
  platform: string
}

type StoreBadgeProps = BadgeProps & {
  store: string
}

type PlatformVisual = {
  icon: LucideIcon
  tone: string
}

const platformVisuals: Record<string, PlatformVisual> = {
  Windows: { icon: Monitor, tone: 'windows' },
  macOS: { icon: Laptop, tone: 'macos' },
  Linux: { icon: Terminal, tone: 'linux' },
  Android: { icon: Smartphone, tone: 'android' },
  iOS: { icon: Smartphone, tone: 'ios' },
  iPadOS: { icon: Tablet, tone: 'ipados' },
  'Nintendo Switch': { icon: Gamepad2, tone: 'nintendo' },
  'Nintendo Switch 2': { icon: Gamepad2, tone: 'nintendo' },
  'PlayStation 4': { icon: Gamepad2, tone: 'playstation' },
  'PlayStation 5': { icon: Gamepad2, tone: 'playstation' },
  'Xbox One': { icon: Gamepad2, tone: 'xbox' },
  'Xbox Series': { icon: Gamepad2, tone: 'xbox' },
}

const storeTones: Record<string, string> = {
  Steam: 'steam',
  'Epic Games Store': 'epic-games',
  'Nintendo eShop': 'nintendo-eshop',
  'Google Play': 'google-play',
  'Apple App Store': 'apple-app-store',
}

export const PlatformBadge = ({ compact = false, label, platform }: PlatformBadgeProps) => {
  const visual = platformVisuals[platform] ?? { icon: Gamepad2, tone: 'other' }
  const Icon = visual.icon

  return <span className={`platform-badge ${visual.tone}${compact ? ' compact' : ''}`} data-platform={platform}>
    <Icon aria-hidden="true" size={compact ? 14 : 16} strokeWidth={2.2} />
    <span>{label ?? platform}</span>
  </span>
}

export const StoreBadge = ({ compact = false, label, store }: StoreBadgeProps) => {
  const tone = storeTones[store] ?? 'other'

  return <span className={`visual-store-badge ${tone}${compact ? ' compact' : ''}`} data-store={store}>
    <ShoppingBag aria-hidden="true" size={compact ? 14 : 16} strokeWidth={2.2} />
    <span>{label ?? store}</span>
  </span>
}
