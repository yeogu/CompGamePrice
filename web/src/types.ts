export interface GameSummary {
  id: string
  title: string
  platforms: string[]
}

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
  startedAt: string
  finishedAt?: string
  errorMessage?: string
}

export interface User { id: number; email: string }
export interface AuthResult { user: User; token: string }
export type AlertRuleType = 'PriceDrop' | 'BelowTargetPrice' | 'NewHistoricalLow' | 'BelowAverage'
export interface AlertRule { id: number; gameId: string; type: AlertRuleType; targetPriceMinor?: number; active: boolean }
export interface Notification { id: number; gameId: string; store: string; productId: string; price: Money; message: string; createdAt: string; read: boolean }
export type OAuthProvider = 'google' | 'kakao' | 'naver'
export interface ExternalIdentity { id: number; provider: 'Google' | 'Kakao' | 'Naver'; email?: string }
