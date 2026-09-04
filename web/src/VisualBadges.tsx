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
  iconOnly?: boolean
  platform: string
}

type StoreBadgeProps = BadgeProps & {
  store: string
}

type PlatformVisual = {
  icon: LucideIcon
  marker?: string
  tone: string
}

const platformVisuals: Record<string, PlatformVisual> = {
  Windows: { icon: Monitor, tone: 'windows' },
  macOS: { icon: Laptop, tone: 'macos' },
  Linux: { icon: Terminal, tone: 'linux' },
  Android: { icon: Smartphone, tone: 'android' },
  iOS: { icon: Smartphone, tone: 'ios' },
  iPadOS: { icon: Tablet, tone: 'ipados' },
  'Nintendo Switch': { icon: Gamepad2, marker: '1', tone: 'nintendo' },
  'Nintendo Switch 2': { icon: Gamepad2, marker: '2', tone: 'nintendo' },
  'PlayStation 4': { icon: Gamepad2, marker: '4', tone: 'playstation' },
  'PlayStation 5': { icon: Gamepad2, marker: '5', tone: 'playstation' },
  'Xbox One': { icon: Gamepad2, marker: '1', tone: 'xbox' },
  'Xbox Series': { icon: Gamepad2, marker: 'X|S', tone: 'xbox' },
}

const storeTones: Record<string, string> = {
  Steam: 'steam',
  'Epic Games Store': 'epic-games',
  'Nintendo eShop': 'nintendo-eshop',
  'Google Play': 'google-play',
  'Apple App Store': 'apple-app-store',
}

export const PlatformBadge = ({ compact = false, iconOnly = false, label, platform }: PlatformBadgeProps) => {
  const visual = platformVisuals[platform] ?? { icon: Gamepad2, tone: 'other' }
  const Icon = visual.icon

  return <span
    aria-label={iconOnly ? platform : undefined}
    className={`platform-badge ${visual.tone}${compact ? ' compact' : ''}${iconOnly ? ' icon-only' : ''}`}
    data-platform={platform}
    role={iconOnly ? 'img' : undefined}
    title={iconOnly ? platform : undefined}
  >
    <Icon aria-hidden="true" size={compact ? 14 : 16} strokeWidth={2.2} />
    {iconOnly && visual.marker && <span aria-hidden="true" className="platform-marker">{visual.marker}</span>}
    {!iconOnly && <span>{label ?? platform}</span>}
  </span>
}

export const StoreBadge = ({ compact = false, label, store }: StoreBadgeProps) => {
  const tone = storeTones[store] ?? 'other'

  return <span className={`visual-store-badge ${tone}${compact ? ' compact' : ''}`} data-store={store}>
    <ShoppingBag aria-hidden="true" size={compact ? 14 : 16} strokeWidth={2.2} />
    <span>{label ?? store}</span>
  </span>
}
