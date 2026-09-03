export interface GameSummary {
  id: string
  title: string
  platforms: string[]
  genres: string[]
  tags: string[]
  aliases: string[]
  developers: string[]
  publishers: string[]
  priceStatus?: 'Available' | 'Collecting' | 'Stale'
  lowestPrice?: Money
  maxDiscountPercent?: number
  lastUpdatedAt?: string
}

export interface CatalogFilterOptions { stores: string[]; platforms: string[]; genres: string[]; tags: string[] }
export type GameSort = 'titleAsc' | 'titleDesc' | 'lowestPrice' | 'updatedDesc' | 'updatedAsc' | 'discountDesc' | 'discountAsc'
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

export interface User { id: number; email: string; role: 'USER' | 'ADMIN' }
export interface AuthResult { user: User; token: string }
export type AlertRuleType = 'PriceDrop' | 'BelowTargetPrice' | 'NewHistoricalLow' | 'BelowAverage'
export interface AlertRule { id: number; gameId: string; gameTitle?: string; type: AlertRuleType; targetPriceMinor?: number; platform?: string; active: boolean }
export interface Notification { id: number; gameId: string; store: string; productId: string; price: Money; message: string; createdAt: string; read: boolean }
export type OAuthProvider = 'google' | 'kakao' | 'naver'
export interface ExternalIdentity { id: number; provider: 'Google' | 'Kakao' | 'Naver'; email?: string }
export interface UserPreferences { emailNotificationsEnabled: boolean; region: 'KR'; currency: 'KRW' }
export type CatalogMatchStatus = 'ApprovedCandidate' | 'NeedsReview' | 'Rejected'
export interface CatalogMatchDecision { status: CatalogMatchStatus; reasons: string[]; titleMatchSource?: string; developerMatched: boolean; publisherMatched?: boolean }
export interface CatalogMetadataDiff { before?: string | string[]; after?: string | string[] }
export interface CatalogMetadataUpdateResult { game: GameSummary; diff: Record<string, CatalogMetadataDiff>; changed: boolean }
export interface CatalogChangeAudit { id: number; actor: string; action: string; store: string; externalProductId: string; gameId: string; outcome: 'APPLIED' | 'NO_OP' | 'PENDING'; occurredAt: string; detail?: string }
export interface AdminStoreQuality {
  store: string
  registeredProducts: number
  pricedProducts: number
  freshPrices: number
  stalePrices: number
  pendingReviews: number
  lastSuccessfulCollectionAt?: string
  catalogProcessed: number
  catalogAccepted: number
  catalogReview: number
  catalogSkippedOrRejected: number
  catalogFailed: number
  catalogAddedLast7Days: number
  lastCatalogSyncAt?: string
}
export interface PeriodicJobStatus {
  job: 'collection' | 'backup'
  enabled: boolean | null
  status: 'NOT_STARTED' | 'UNKNOWN' | 'DISABLED' | 'WAITING' | 'RUNNING' | 'SUCCEEDED' | 'PARTIAL_FAILURE' | 'FAILED'
  updatedAt?: string | null
  lastStartedAt?: string | null
  lastFinishedAt?: string | null
  nextRunAt?: string | null
  failedSteps?: string[]
  lastBackup?: string | null
  removedFiles?: number
  error?: string | null
}
export interface AdminHealthSummary {
  metadata: { complete: number; incomplete: number; total: number }
  collection: { recentFailures: number; lastFailure?: { store: string; error?: string; startedAt: string } }
  stores: AdminStoreQuality[]
  notifications: { pending: number; retryable: number; exhausted: number; sent: number }
  emails: { pending: number; retryable: number; exhausted: number; sent: number; lastError?: string | null; lastAttemptAt?: string | null }
  automation: { collection: PeriodicJobStatus; backup: PeriodicJobStatus }
}
export interface MetadataReview { gameId: string; sourceStore: string; externalProductId: string; proposed: { developers: string[]; publishers: string[]; genres: string[] }; diff: Record<string, CatalogMetadataDiff>; status: 'PENDING' | 'APPROVED' | 'REJECTED'; createdAt: string; resolvedAt?: string }
export interface MetadataSyncStatus { autoApplied?: number; discovered?: number; failed?: Array<{ gameId: string; error: string }>; pendingReviews: MetadataReview[]; reviewHistory: MetadataReview[] }
export interface CatalogAdminResult {
  game: {
    id: string
    title: string
    platforms?: string[]
    developers?: string[]
    publishers?: string[]
    products: Array<{ store: string; productId: string; productUrl: string }>
    matchedProduct?: { store: string; productId: string; productUrl?: string; title?: string; developer?: string; priceMinor?: number; currency?: string }
    matchDecision?: CatalogMatchDecision
  }
  applied: boolean
  requiresApiRestart: boolean
}
export interface CatalogCollectionJob { id: number; store?: string; status: 'IDLE' | 'RUNNING' | 'SUCCEEDED' | 'FAILED'; error?: string }
export interface StoreProductCandidate { store: string; externalProductId: string; title: string; productUrl: string; platforms: string[]; developer?: string; priceMinor?: number; currency?: string }
export interface CatalogSyncReview { externalProductId: string; title: string; reason: string; status: 'PENDING' | 'APPROVED' | 'REJECTED'; createdAt: string }
export interface MobileCatalogSyncReview extends CatalogSyncReview { gameId: string; decision: CatalogMatchStatus; productUrl?: string }
export interface MobileCatalogSyncFailure { gameId: string; title?: string; reason: string }
export interface MobileCatalogSyncExclusion extends MobileCatalogSyncFailure { externalProductId?: string; productUrl?: string }
export interface MobileCatalogSyncRun { id: number; status: string; startedAt: string; finishedAt?: string; processed: number; approvedCandidates: number; autoConnected?: number; needsReview: number; rejected: number; failed: number; retries: number; error?: string; reasonCounts: Record<string, number>; failures?: MobileCatalogSyncFailure[]; exclusions?: MobileCatalogSyncExclusion[] }
export interface MobileCatalogSyncJob { provider: 'GooglePlay' | 'AppleAppStore' | 'NintendoEShop'; status?: 'IDLE' | 'RUNNING' | 'SUCCEEDED' | 'PARTIAL' | 'FAILED'; pendingReviews: MobileCatalogSyncReview[]; reviewHistory: MobileCatalogSyncReview[]; recentRuns: MobileCatalogSyncRun[] }
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
