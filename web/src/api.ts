import type { AlertRule, AlertRuleType, AuthResult, CollectionRun, ExternalIdentity, GamePriceHistoryResponse, GamePriceResponse, GameSummary, Notification, OAuthProvider, User } from './types'

const apiBaseUrl = import.meta.env.VITE_API_URL ?? 'http://127.0.0.1:8080'

async function requestJson<T>(path: string, init: RequestInit = {}, token = ''): Promise<T> {
  const response = await fetch(`${apiBaseUrl}${path}`, {
    ...init,
    headers: { ...(init.body ? { 'Content-Type': 'application/json' } : {}), ...(token ? { Authorization: `Bearer ${token}` } : {}), ...init.headers },
  })
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { error?: string } | null
    throw new Error(body?.error ?? `API request failed (${response.status})`)
  }
  return response.json() as Promise<T>
}
const getJson = <T,>(path: string) => requestJson<T>(path)

export async function getGames(query = ''): Promise<GameSummary[]> {
  const search = query ? `?query=${encodeURIComponent(query)}` : ''
  const result = await getJson<{ games: GameSummary[] }>(
    `/api/games${search}`,
  )
  return result.games
}

export function getGamePrices(
  gameId: string,
  platform = '',
): Promise<GamePriceResponse> {
  const query = platform ? `?platform=${encodeURIComponent(platform)}` : ''
  return getJson<GamePriceResponse>(
    `/api/games/${encodeURIComponent(gameId)}/prices${query}`,
  )
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

export const register = (email: string, password: string) => requestJson<AuthResult>('/api/auth/register', { method: 'POST', body: JSON.stringify({ email, password }) })
export const login = (email: string, password: string) => requestJson<AuthResult>('/api/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) })
export const getMe = (token: string) => requestJson<User>('/api/auth/me', {}, token)
export const logout = (token: string) => requestJson<object>('/api/auth/logout', { method: 'POST' }, token)
export const getAlertRules = async (token: string) => (await requestJson<{ rules: AlertRule[] }>('/api/alert-rules', {}, token)).rules
export const addAlertRule = (token: string, gameId: string, type: AlertRuleType, targetPriceMinor?: number) => requestJson<{ id: number }>('/api/alert-rules', { method: 'POST', body: JSON.stringify({ gameId, type, ...(targetPriceMinor !== undefined ? { targetPriceMinor } : {}) }) }, token)
export const deleteAlertRule = (token: string, id: number) => requestJson<object>(`/api/alert-rules/${id}`, { method: 'DELETE' }, token)
export const getNotifications = async (token: string) => (await requestJson<{ notifications: Notification[] }>('/api/notifications', {}, token)).notifications
export const markNotificationRead = (token: string, id: number) => requestJson<object>(`/api/notifications/${id}/read`, { method: 'PATCH' }, token)
export const getOAuthUrl = async (provider: OAuthProvider, token = '', link = false) => (await requestJson<{ authorizationUrl: string }>(`/api/oauth/${provider}/start${link ? '?link=true' : ''}`, {}, token)).authorizationUrl
export const getExternalIdentities = async (token: string) => (await requestJson<{ identities: ExternalIdentity[] }>('/api/external-identities', {}, token)).identities
export const unlinkExternalIdentity = (token: string, id: number) => requestJson<object>(`/api/external-identities/${id}`, { method: 'DELETE' }, token)
