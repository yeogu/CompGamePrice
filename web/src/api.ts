import type { AlertRule, AlertRuleType, AuthResult, CatalogAdminResult, CatalogCollectionJob, CatalogFilterOptions, CatalogSyncJob, CollectionRun, ExternalIdentity, GameCatalogFilters, GameCatalogPage, GamePriceHistoryResponse, GamePriceResponse, GameSummary, Notification, OAuthProvider, StoreProductCandidate, User, UserPreferences } from './types'

const apiBaseUrl = import.meta.env.VITE_API_URL ?? 'http://127.0.0.1:8080'

async function requestJson<T>(path: string, init: RequestInit = {}, token = ''): Promise<T> {
  const response = await fetch(`${apiBaseUrl}${path}`, {
    ...init,
    credentials: 'include',
    headers: { ...(init.body ? { 'Content-Type': 'application/json' } : {}), ...(token && token !== 'cookie' ? { Authorization: `Bearer ${token}` } : {}), ...init.headers },
  })
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { error?: string } | null
    throw new Error(body?.error ?? `API request failed (${response.status})`)
  }
  return response.json() as Promise<T>
}
const getJson = <T,>(path: string) => requestJson<T>(path)

export async function getGamePage(query = '', filters: GameCatalogFilters = {}): Promise<GameCatalogPage> {
  const parameters = new URLSearchParams()
  if (query) {
    parameters.set('query', query)
  }
  if (filters.store) {
    parameters.set('store', filters.store)
  }
  if (filters.platform) {
    parameters.set('platform', filters.platform)
  }
  if (filters.genre) {
    parameters.set('genre', filters.genre)
  }
  if (filters.tag) {
    parameters.set('tag', filters.tag)
  }
  if (filters.page) {
    parameters.set('page', String(filters.page))
  }
  if (filters.pageSize) {
    parameters.set('pageSize', String(filters.pageSize))
  }
  if (filters.sort) {
    parameters.set('sort', filters.sort)
  }
  const search = parameters.size > 0 ? `?${parameters}` : ''
  return getJson<GameCatalogPage>(
    `/api/games${search}`,
  )
}

export async function getGames(query = '', filters: GameCatalogFilters = {}): Promise<GameSummary[]> {
  return (await getGamePage(query, filters)).games
}

export const getCatalogFilters = () => getJson<CatalogFilterOptions>('/api/catalog/filters')

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
  platform = '',
): Promise<GamePriceHistoryResponse> {
  const parameters = new URLSearchParams()
  if (since) parameters.set('since', since)
  if (platform) parameters.set('platform', platform)
  const query = parameters.size > 0 ? `?${parameters}` : ''
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
export const addAlertRule = (token: string, gameId: string, type: AlertRuleType, targetPriceMinor?: number, platform?: string) => requestJson<{ id: number }>('/api/alert-rules', { method: 'POST', body: JSON.stringify({ gameId, type, ...(targetPriceMinor !== undefined ? { targetPriceMinor } : {}), ...(platform ? { platform } : {}) }) }, token)
export const deleteAlertRule = (token: string, id: number) => requestJson<object>(`/api/alert-rules/${id}`, { method: 'DELETE' }, token)
export const getNotifications = async (token: string) => (await requestJson<{ notifications: Notification[] }>('/api/notifications', {}, token)).notifications
export const markNotificationRead = (token: string, id: number) => requestJson<object>(`/api/notifications/${id}/read`, { method: 'PATCH' }, token)
export const getOAuthUrl = async (provider: OAuthProvider, token = '', link = false) => (await requestJson<{ authorizationUrl: string }>(`/api/oauth/${provider}/start${link ? '?link=true' : ''}`, {}, token)).authorizationUrl
export const getExternalIdentities = async (token: string) => (await requestJson<{ identities: ExternalIdentity[] }>('/api/external-identities', {}, token)).identities
export const unlinkExternalIdentity = (token: string, id: number) => requestJson<object>(`/api/external-identities/${id}`, { method: 'DELETE' }, token)
export const getFavorites = async (token: string) => (await requestJson<{ games: GameSummary[] }>('/api/favorites', {}, token)).games
export const addFavorite = (token: string, gameId: string) => requestJson<{ gameId: string }>('/api/favorites', { method: 'POST', body: JSON.stringify({ gameId }) }, token)
export const deleteFavorite = (token: string, gameId: string) => requestJson<object>(`/api/favorites/${encodeURIComponent(gameId)}`, { method: 'DELETE' }, token)
export const getPreferences = (token: string) => requestJson<UserPreferences>('/api/account/preferences', {}, token)
export const updatePreferences = (token: string, preferences: UserPreferences) => requestJson<UserPreferences>('/api/account/preferences', { method: 'PATCH', body: JSON.stringify(preferences) }, token)
export const getCatalogAdminStatus = () => requestJson<{ enabled: boolean }>('/api/admin/catalog/status')
export const importSteamCatalogGame = (appId: string, gameId: string, apply: boolean) => requestJson<CatalogAdminResult>('/api/admin/catalog/steam', { method: 'POST', body: JSON.stringify({ appId, ...(gameId ? { gameId } : {}), apply }) })
export const getCatalogCollectionJob = () => requestJson<CatalogCollectionJob>('/api/admin/catalog/collection')
export const startCatalogCollection = () => requestJson<CatalogCollectionJob>('/api/admin/catalog/collection', { method: 'POST' })
export const searchStoreCandidates = async (store: string, query: string) => (await requestJson<{ candidates: StoreProductCandidate[] }>(`/api/admin/catalog/candidates?store=${encodeURIComponent(store)}&query=${encodeURIComponent(query)}`)).candidates
export const getCatalogSyncJob = () => requestJson<CatalogSyncJob>('/api/admin/catalog/sync')
export const startCatalogSync = (batchSize: number) => requestJson<CatalogSyncJob>('/api/admin/catalog/sync', { method: 'POST', body: JSON.stringify({ batchSize }) })
export const resolveCatalogSyncReview = (appId: string, resolution: 'APPROVED' | 'REJECTED') => requestJson<CatalogSyncJob>(`/api/admin/catalog/sync/reviews/${encodeURIComponent(appId)}`, { method: 'PATCH', body: JSON.stringify({ resolution }) })
export const requestCatalogGame = (query: string) => requestJson<{ query: string; status: string; requestCount: number }>('/api/catalog-requests', { method: 'POST', body: JSON.stringify({ query }) })
