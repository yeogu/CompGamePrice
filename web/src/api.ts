import type { CollectionRun, GamePriceHistoryResponse, GamePriceResponse, GameSummary } from './types'

const apiBaseUrl = import.meta.env.VITE_API_URL ?? 'http://127.0.0.1:8080'

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${apiBaseUrl}${path}`)
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { error?: string } | null
    throw new Error(body?.error ?? `API request failed (${response.status})`)
  }
  return response.json() as Promise<T>
}

export async function searchGames(query: string): Promise<GameSummary[]> {
  const result = await getJson<{ games: GameSummary[] }>(
    `/api/games?query=${encodeURIComponent(query)}`,
  )
  return result.games
}

export function getGamePrices(gameId: string): Promise<GamePriceResponse> {
  return getJson<GamePriceResponse>(`/api/games/${encodeURIComponent(gameId)}/prices`)
}

export function getGamePriceHistory(
  gameId: string,
  since?: string,
): Promise<GamePriceHistoryResponse> {
  const query = since ? `?since=${encodeURIComponent(since)}` : ''
  return getJson<GamePriceHistoryResponse>(
    `/api/games/${encodeURIComponent(gameId)}/price-history${query}`,
  )
}

export async function getCollectionRuns(limit = 6): Promise<CollectionRun[]> {
  const result = await getJson<{ runs: CollectionRun[] }>(
    `/api/collection-runs?limit=${limit}`,
  )
  return result.runs
}
