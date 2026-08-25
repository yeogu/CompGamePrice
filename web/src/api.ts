import type { GamePriceResponse, GameSummary } from './types'

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
