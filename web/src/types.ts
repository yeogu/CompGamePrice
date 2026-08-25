export interface GameSummary {
  id: string
  title: string
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
  price: Money
  purchasable: boolean
  platforms: string[]
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
