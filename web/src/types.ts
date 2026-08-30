export interface GameSummary {
  id: string
  title: string
  platforms: string[]
  genres: string[]
  tags: string[]
  priceStatus?: 'Available' | 'Collecting' | 'Stale'
  lowestPrice?: Money
  lastUpdatedAt?: string
}

export interface CatalogFilterOptions { stores: string[]; platforms: string[]; genres: string[]; tags: string[] }
export type GameSort = 'title' | 'lowestPrice' | 'recentlyUpdated'
export interface GameCatalogFilters { store?: string; platform?: string; genre?: string; tag?: string; page?: number; pageSize?: number; sort?: GameSort }
export interface GameCatalogPage { games: GameSummary[]; page: number; pageSize: number; total: number }

export interface Money {
  minorAmount: number
  currency: string
}

export interface PriceHistory {
  lowestPrice: Money
  highestPrice: Money
  averagePrice: Money
  trend: string
  observationCount: number
}

export interface Recommendation {
  rating: string
  reasons: string[]
  amountAboveHistoricalLow: number
  percentAboveHistoricalLow: number
  percentComparedToAverage: number
  priceRangePositionPercent?: number
}

export interface StoreProduct {
  productId: string
  store: string
  purchaseUrl: string
  region: string
  edition: string
  offerType: string
  price: Money
  regularPrice?: Money
  discountPercent: number
  purchasable: boolean
  lastCheckedAt?: string
  lastSuccessfulCheckAt?: string
  freshness: 'Fresh' | 'Stale' | 'Unknown'
  stale: boolean
  platforms: string[]
  compatibility: { platform: string; status: string }[]
  history?: PriceHistory
  recommendation?: Recommendation
}

export interface GamePriceResponse {
  game: GameSummary
  products: StoreProduct[]
  cheapest?: {
    productId: string
    store: string
    price: Money
  }
}

export interface PriceObservation {
  price: Money
  regularPrice?: Money
  discountPercent: number
  purchasable: boolean
  observedAt: string
}

export interface ProductPriceHistory {
  productId: string
  store: string
  observations: PriceObservation[]
}

export interface GamePriceHistoryResponse {
  game: GameSummary
  histories: ProductPriceHistory[]
}

export interface CollectionRun {
  id: number
  store: string
  status: 'RUNNING' | 'SUCCEEDED' | 'FAILED'
  productsFound: number
  productsRejected: number
  productsFailed: number
  retryCount: number
  startedAt: string
  finishedAt?: string
  errorMessage?: string
}

export interface User { id: number; email: string }
export interface AuthResult { user: User; token: string }
export type AlertRuleType = 'PriceDrop' | 'BelowTargetPrice' | 'NewHistoricalLow' | 'BelowAverage'
export interface AlertRule { id: number; gameId: string; gameTitle?: string; type: AlertRuleType; targetPriceMinor?: number; platform?: string; active: boolean }
export interface Notification { id: number; gameId: string; store: string; productId: string; price: Money; message: string; createdAt: string; read: boolean }
export type OAuthProvider = 'google' | 'kakao' | 'naver'
export interface ExternalIdentity { id: number; provider: 'Google' | 'Kakao' | 'Naver'; email?: string }
export interface UserPreferences { emailNotificationsEnabled: boolean; region: 'KR'; currency: 'KRW' }
export interface CatalogAdminResult { game: GameSummary & { products: Array<{ store: string; productId: string; productUrl: string }>; matchedProduct?: { store: string; productId: string; developer?: string; priceMinor?: number; currency?: string } }; applied: boolean; requiresApiRestart: boolean }
export interface CatalogCollectionJob { id: number; store?: string; status: 'IDLE' | 'RUNNING' | 'SUCCEEDED' | 'FAILED'; error?: string }
export interface StoreProductCandidate { store: string; externalProductId: string; title: string; productUrl: string; platforms: string[] }
export interface CatalogSyncReview { externalProductId: string; title: string; reason: string; status: 'PENDING' | 'APPROVED' | 'REJECTED'; createdAt: string }
export interface CatalogGameRequest { query: string; status: string; requestCount: number; requestedAt: string; error?: string }
export interface CatalogSyncRun { id: number; status: string; startedAt: string; finishedAt?: string; processed: number; accepted: number; review: number; skipped: number; failed: number; error?: string }
export interface CatalogSyncJob {
  provider: string
  status: 'IDLE' | 'RUNNING' | 'SUCCEEDED' | 'FAILED'
  accepted: number
  review: number
  skipped: number
  failed: number
  processed?: number
  lastAppId?: string
  error?: string
  pendingReviews?: CatalogSyncReview[]
  reviewHistory?: CatalogSyncReview[]
  gameRequests?: CatalogGameRequest[]
  recentRuns?: CatalogSyncRun[]
  priceCollection?: {
    status: 'NOT_REQUIRED' | 'RUNNING' | 'SUCCEEDED' | 'FAILED'
    attemptedAt?: string
    exitCode?: number
    error?: string
  }
}
