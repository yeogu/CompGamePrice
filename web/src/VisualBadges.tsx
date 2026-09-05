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
  label?: string
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
  NintendoSwitch: { icon: Gamepad2, label: 'Nintendo Switch', marker: '1', tone: 'nintendo' },
  NintendoSwitch2: { icon: Gamepad2, label: 'Nintendo Switch 2', marker: '2', tone: 'nintendo' },
  'PlayStation 4': { icon: Gamepad2, marker: '4', tone: 'playstation' },
  'PlayStation 5': { icon: Gamepad2, marker: '5', tone: 'playstation' },
  'Xbox One': { icon: Gamepad2, marker: '1', tone: 'xbox' },
  'Xbox Series X|S': { icon: Gamepad2, marker: 'X|S', tone: 'xbox' },
  PlayStation4: { icon: Gamepad2, label: 'PlayStation 4', marker: '4', tone: 'playstation' },
  PlayStation5: { icon: Gamepad2, label: 'PlayStation 5', marker: '5', tone: 'playstation' },
  XboxOne: { icon: Gamepad2, label: 'Xbox One', marker: '1', tone: 'xbox' },
  XboxSeries: { icon: Gamepad2, label: 'Xbox Series X|S', marker: 'X|S', tone: 'xbox' },
}

const storeVisuals: Record<string, { label?: string, tone: string }> = {
  Steam: { tone: 'steam' },
  'Epic Games Store': { tone: 'epic-games' },
  EpicGamesStore: { label: 'Epic Games Store', tone: 'epic-games' },
  'Nintendo eShop': { tone: 'nintendo-eshop' },
  NintendoEShop: { label: 'Nintendo eShop', tone: 'nintendo-eshop' },
  'Google Play': { tone: 'google-play' },
  GooglePlay: { label: 'Google Play', tone: 'google-play' },
  'Apple App Store': { tone: 'apple-app-store' },
  AppleAppStore: { label: 'Apple App Store', tone: 'apple-app-store' },
  'PlayStation Store': { tone: 'playstation-store' },
  PlayStationStore: { label: 'PlayStation Store', tone: 'playstation-store' },
  'Microsoft Store': { tone: 'microsoft-store' },
  MicrosoftStore: { label: 'Microsoft Store', tone: 'microsoft-store' },
}

export const PlatformBadge = ({ compact = false, iconOnly = false, label, platform }: PlatformBadgeProps) => {
  const visual = platformVisuals[platform] ?? { icon: Gamepad2, tone: 'other' }
  const displayLabel = label ?? visual.label ?? platform
  const Icon = visual.icon

  return <span
    aria-label={iconOnly ? displayLabel : undefined}
    className={`platform-badge ${visual.tone}${compact ? ' compact' : ''}${iconOnly ? ' icon-only' : ''}`}
    data-platform={platform}
    role={iconOnly ? 'img' : undefined}
    title={iconOnly ? displayLabel : undefined}
  >
    <Icon aria-hidden="true" size={compact ? 14 : 16} strokeWidth={2.2} />
    {iconOnly && visual.marker && <span aria-hidden="true" className="platform-marker">{visual.marker}</span>}
    {!iconOnly && <span>{displayLabel}</span>}
  </span>
}

export const StoreBadge = ({ compact = false, label, store }: StoreBadgeProps) => {
  const visual = storeVisuals[store] ?? { tone: 'other' }
  const displayLabel = label ?? visual.label ?? store

  return <span className={`visual-store-badge ${visual.tone}${compact ? ' compact' : ''}`} data-store={store}>
    <ShoppingBag aria-hidden="true" size={compact ? 14 : 16} strokeWidth={2.2} />
    <span>{displayLabel}</span>
  </span>
}
