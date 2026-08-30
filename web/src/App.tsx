import { FormEvent, KeyboardEvent, useEffect, useRef, useState } from 'react'
import { addAlertRule, addFavorite, deleteAlertRule, deleteFavorite, getAlertRules, getCatalogAdminStatus, getCatalogCollectionJob, getCatalogFilters, getCatalogSyncJob, getCollectionRuns, getExternalIdentities, getFavorites, getGamePage, getGamePriceHistory, getGamePrices, getGames, getMe, getNotifications, getOAuthUrl, getPreferences, importGooglePlayCatalogGame, importSteamCatalogGame, login, logout, markNotificationRead, register, requestCatalogGame, resolveCatalogSyncReview, searchStoreCandidates, startCatalogCollection, startCatalogSync, unlinkExternalIdentity, updatePreferences } from './api'
import PriceHistoryChart from './PriceHistoryChart'
import type { AlertRule, AlertRuleType, CatalogAdminResult, CatalogCollectionJob, CatalogFilterOptions, CatalogSyncJob, CollectionRun, ExternalIdentity, GameCatalogFilters, GamePriceHistoryResponse, GamePriceResponse, GameSort, GameSummary, Money, Notification, OAuthProvider, StoreProductCandidate, User, UserPreferences } from './types'

const formatMoney = (money: Money) =>
  new Intl.NumberFormat('ko-KR', {
    style: 'currency',
    currency: money.currency,
    maximumFractionDigits: 0,
  }).format(money.minorAmount)

const recommendationLabel: Record<string, string> = {
  StrongBuy: '구매 추천',
  Buy: '구매 고려',
  Wait: '조금 더 기다리기',
  InsufficientData: '데이터 수집 중',
}

const recommendationReason: Record<string, string> = {
  'Current price is the historical low.': '현재 가격이 수집된 기간의 최저가입니다.',
  'Price fell since the previous observation.': '직전 관측보다 가격이 내려갔습니다.',
  'Price rose since the previous observation.': '직전 관측보다 가격이 올랐습니다.',
  'Current price is at or above the observed average.': '현재 가격이 관측 평균 이상입니다.',
  'Current price is not close enough to the historical low.': '현재 가격이 역대 최저가와 충분히 가깝지 않습니다.',
}

const authenticationErrorMessage = (reason: unknown, mode: 'login' | 'register') => {
  const message = reason instanceof Error ? reason.message : ''
  if (message === 'Failed to fetch' || message.includes('NetworkError')) {
    return '서버와 일시적으로 연결되지 않았습니다. 잠시 후 다시 시도해주세요.'
  }
  if (message === 'invalid credentials') {
    return '이메일 또는 비밀번호가 올바르지 않습니다.'
  }
  if (message.includes('too many login attempts')) {
    return '로그인 시도가 너무 많습니다. 15분 후 다시 시도해주세요.'
  }
  if (message.includes('already') || message.includes('could not be created')) {
    return '이미 가입된 이메일이거나 계정을 만들 수 없습니다.'
  }
  if (message.includes('password')) {
    return '비밀번호는 8자 이상이어야 합니다.'
  }
  if (message.includes('email')) {
    return '올바른 이메일 주소를 입력해주세요.'
  }
  if (message) {
    return message
  }
  return mode === 'login'
    ? '로그인에 실패했습니다. 잠시 후 다시 시도해주세요.'
    : '회원가입에 실패했습니다. 잠시 후 다시 시도해주세요.'
}

const canonicalIdFromTitle = (title: string) => title
  .toLowerCase()
  .replace(/[^a-z0-9]+/g, '-')
  .replace(/^-|-$/g, '')

type AppView = 'games' | 'favorites' | 'alerts' | 'notifications' | 'account' | 'collection' | 'admin'

function App() {
  const [query, setQuery] = useState('')
  const [games, setGames] = useState<GameSummary[]>([])
  const [report, setReport] = useState<GamePriceResponse | null>(null)
  const [history, setHistory] = useState<GamePriceHistoryResponse | null>(null)
  const [selectedGameId, setSelectedGameId] = useState('')
  const [selectedPlatform, setSelectedPlatform] = useState('')
  const [collectionRuns, setCollectionRuns] = useState<CollectionRun[]>([])
  const [collectionStatusError, setCollectionStatusError] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const requestSequence = useRef(0)
  const [token, setToken] = useState(() => new URLSearchParams(window.location.hash.slice(1)).get('oauth') === 'success' || localStorage.getItem('game-price-session') === '1' ? 'cookie' : '')
  const [user, setUser] = useState<User | null>(null)
  const [authMode, setAuthMode] = useState<'login' | 'register'>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [rules, setRules] = useState<AlertRule[]>([])
  const [notifications, setNotifications] = useState<Notification[]>([])
  const [targetPrice, setTargetPrice] = useState('')
  const [identities, setIdentities] = useState<ExternalIdentity[]>([])
  const [favorites, setFavorites] = useState<GameSummary[]>([])
  const [preferences, setPreferences] = useState<UserPreferences>({ emailNotificationsEnabled: true, region: 'KR', currency: 'KRW' })
  const [catalogAdminEnabled, setCatalogAdminEnabled] = useState(false)
  const [adminAppId, setAdminAppId] = useState('')
  const [adminGameId, setAdminGameId] = useState('')
  const [adminResult, setAdminResult] = useState<CatalogAdminResult | null>(null)
  const [catalogJob, setCatalogJob] = useState<CatalogCollectionJob | null>(null)
  const [catalogSyncJob, setCatalogSyncJob] = useState<CatalogSyncJob | null>(null)
  const [catalogSyncBatchSize, setCatalogSyncBatchSize] = useState(20)
  const [reviewingAppId, setReviewingAppId] = useState('')
  const [adminQueueView, setAdminQueueView] = useState<'pending' | 'history' | 'requests' | 'runs'>('pending')
  const [adminStore, setAdminStore] = useState('Steam')
  const [adminQuery, setAdminQuery] = useState('')
  const [adminCandidates, setAdminCandidates] = useState<StoreProductCandidate[]>([])
  const [adminSearching, setAdminSearching] = useState(false)
  const [adminImporting, setAdminImporting] = useState(false)
  const [adminError, setAdminError] = useState('')
  const [pendingCandidate, setPendingCandidate] = useState<StoreProductCandidate | null>(null)
  const [actionMessage, setActionMessage] = useState('')
  const [activeView, setActiveView] = useState<AppView>('games')
  const [authOpen, setAuthOpen] = useState(false)
  const [authError, setAuthError] = useState('')
  const [authSubmitting, setAuthSubmitting] = useState(false)
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [showGameResults, setShowGameResults] = useState(false)
  const [suggestions, setSuggestions] = useState<GameSummary[]>([])
  const [suggestionsOpen, setSuggestionsOpen] = useState(false)
  const [activeSuggestion, setActiveSuggestion] = useState(-1)
  const [catalogRequestSubmitting, setCatalogRequestSubmitting] = useState(false)
  const [catalogRequestMessage, setCatalogRequestMessage] = useState('')
  const [catalogFilters, setCatalogFilters] = useState<CatalogFilterOptions>({ stores: [], platforms: [], genres: [], tags: [] })
  const initialParameters = new URLSearchParams(window.location.search)
  const [selectedStore, setSelectedStore] = useState(initialParameters.get('store') ?? '')
  const [browsePlatform, setBrowsePlatform] = useState(initialParameters.get('browsePlatform') ?? '')
  const [selectedGenre, setSelectedGenre] = useState(initialParameters.get('genre') ?? '')
  const [selectedTag, setSelectedTag] = useState(initialParameters.get('tag') ?? '')
  const [gameSort, setGameSort] = useState<GameSort>((initialParameters.get('sort') as GameSort) || 'title')
  const [catalogPage, setCatalogPage] = useState(1)
  const [catalogTotal, setCatalogTotal] = useState(0)
  const [browseMode, setBrowseMode] = useState(false)
  const autocompleteRef = useRef<HTMLDivElement>(null)
  const suggestionSequence = useRef(0)

  const refreshAccount = async (activeToken: string) => {
    const [me, nextRules, nextNotifications, nextIdentities] = await Promise.all([
      getMe(activeToken),
      getAlertRules(activeToken),
      getNotifications(activeToken),
      getExternalIdentities(activeToken),
    ])
    const [nextFavorites, nextPreferences] = await Promise.all([
      getFavorites(activeToken).catch(() => []),
      getPreferences(activeToken).catch(() => ({
        emailNotificationsEnabled: true,
        region: 'KR' as const,
        currency: 'KRW' as const,
      })),
    ])
    setUser({ ...me, email: nextIdentities[0]?.email ?? me.email })
    setRules(nextRules)
    setNotifications(nextNotifications)
    setIdentities(nextIdentities)
    setFavorites(nextFavorites)
    setPreferences(nextPreferences)
  }

  const submitAuth = async (event: FormEvent) => {
    event.preventDefault()
    setAuthError('')
    setAuthSubmitting(true)
    try {
      const result = authMode === 'register' ? await register(email, password) : await login(email, password)
      localStorage.setItem('game-price-session', '1')
      setToken('cookie')
      setUser(result.user)
      setPassword('')
      await refreshAccount('cookie')
      setAuthOpen(false)
      setActionMessage(authMode === 'login' ? '로그인했습니다.' : '회원가입과 로그인이 완료되었습니다.')
    } catch (reason) {
      setAuthError(authenticationErrorMessage(reason, authMode))
    } finally {
      setAuthSubmitting(false)
    }
  }

  const openAuth = (mode: 'login' | 'register') => {
    setAuthMode(mode)
    setAuthError('')
    setAuthOpen(true)
  }

  const navigate = (view: AppView) => {
    setActiveView(view)
    setSidebarOpen(false)
  }

  const openGameFinder = () => {
    navigate('games')
    setQuery('')
    setSelectedGameId('')
    setSelectedPlatform('')
    setReport(null)
    setHistory(null)
    setShowGameResults(false)
    setSuggestions([])
    setSuggestionsOpen(false)
    setSelectedStore('')
    setBrowsePlatform('')
    setSelectedGenre('')
    setSelectedTag('')
    setBrowseMode(false)
    const address = new URL(window.location.href)
    address.searchParams.delete('game')
    address.searchParams.delete('platform')
    window.history.replaceState(null, '', address)
  }

  const chooseSuggestion = (game: GameSummary) => {
    setBrowseMode(false)
    setQuery(game.title)
    setGames([game])
    setSuggestionsOpen(false)
    setActiveSuggestion(-1)
    setShowGameResults(true)
    void selectGame(game)
  }

  const handleAutocompleteKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (!suggestionsOpen || suggestions.length === 0) {
      if (event.key === 'Escape') {
        setSuggestionsOpen(false)
      }
      return
    }
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setActiveSuggestion((current) => (current + 1) % suggestions.length)
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setActiveSuggestion((current) => current <= 0 ? suggestions.length - 1 : current - 1)
    } else if (event.key === 'Enter' && activeSuggestion >= 0) {
      event.preventDefault()
      chooseSuggestion(suggestions[activeSuggestion])
    } else if (event.key === 'Escape') {
      setSuggestionsOpen(false)
      setActiveSuggestion(-1)
    }
  }

  const submitCatalogRequest = async () => {
    const requestedQuery = query.trim()
    if (requestedQuery.length < 2) {
      return
    }
    setCatalogRequestSubmitting(true)
    setCatalogRequestMessage('')
    try {
      const request = await requestCatalogGame(requestedQuery)
      setCatalogRequestMessage(`등록 요청이 접수됐습니다. 요청 횟수 ${request.requestCount}회`)
    } catch (reason) {
      setCatalogRequestMessage(reason instanceof Error ? reason.message : '게임 등록을 요청하지 못했습니다.')
    } finally {
      setCatalogRequestSubmitting(false)
    }
  }

  const browseCatalog = async (filters: GameCatalogFilters) => {
    const requestId = ++requestSequence.current
    setLoading(true)
    setError('')
    setSelectedGameId('')
    setSelectedPlatform('')
    setReport(null)
    setHistory(null)
    setShowGameResults(true)
    setBrowseMode(true)
    try {
      const result = await getGamePage('', { pageSize: 12, ...filters })
      if (requestId === requestSequence.current) {
        setGames(result.games)
        setCatalogPage(result.page)
        setCatalogTotal(result.total)
        const address = new URL(window.location.href)
        const urlValues = {
          store: filters.store,
          browsePlatform: filters.platform,
          genre: filters.genre,
          tag: filters.tag,
          sort: filters.sort === 'title' ? undefined : filters.sort,
        }
        Object.entries(urlValues).forEach(([name, value]) => {
          if (value) {
            address.searchParams.set(name, value)
          } else {
            address.searchParams.delete(name)
          }
        })
        address.searchParams.delete('game')
        address.searchParams.delete('platform')
        window.history.replaceState(null, '', address)
      }
    } catch (reason) {
      if (requestId === requestSequence.current) {
        setError(reason instanceof Error ? reason.message : '게임 카탈로그를 탐색하지 못했습니다.')
      }
    } finally {
      if (requestId === requestSequence.current) {
        setLoading(false)
      }
    }
  }

  const applyDetailedFilters = (event: FormEvent) => {
    event.preventDefault()
    void browseCatalog({
      store: selectedStore || undefined,
      platform: browsePlatform || undefined,
      genre: selectedGenre || undefined,
      tag: selectedTag || undefined,
      sort: gameSort,
      page: 1,
    })
  }

  const applyQuickPlatform = (platform: string) => {
    setSelectedStore('')
    setBrowsePlatform(platform)
    setSelectedGenre('')
    setSelectedTag('')
    void browseCatalog({ platform, sort: gameSort, page: 1 })
  }

  const activeBrowseFilters = {
    store: selectedStore,
    platform: browsePlatform,
    genre: selectedGenre,
    tag: selectedTag,
  }

  const clearBrowseFilter = (name: keyof typeof activeBrowseFilters) => {
    const next = { ...activeBrowseFilters, [name]: '' }
    setSelectedStore(next.store)
    setBrowsePlatform(next.platform)
    setSelectedGenre(next.genre)
    setSelectedTag(next.tag)
    void browseCatalog({
      store: next.store || undefined,
      platform: next.platform || undefined,
      genre: next.genre || undefined,
      tag: next.tag || undefined,
      sort: gameSort,
      page: 1,
    })
  }

  const signOut = async () => {
    await logout(token)
    localStorage.removeItem('game-price-session')
    setToken('')
    setUser(null)
    setRules([])
    setNotifications([])
    setIdentities([])
    setFavorites([])
    navigate('games')
  }

  const createRule = async (type: AlertRuleType) => {
    if (!token || !selectedGameId) return
    setError(''); setActionMessage('')
    const amount = type === 'BelowTargetPrice' && targetPrice.trim() !== '' ? Number(targetPrice) : undefined
    if (type === 'BelowTargetPrice' && (!Number.isInteger(amount) || (amount ?? 0) <= 0 || (amount ?? 0) > 1_000_000_000)) {
      setError('목표 가격을 1원 이상 10억원 이하의 정수로 입력해주세요.'); return
    }
    try { await addAlertRule(token, selectedGameId, type, amount, selectedPlatform || undefined); setRules(await getAlertRules(token)); setTargetPrice(''); setActionMessage('알림 규칙을 등록했습니다.') }
    catch (reason) { setError(reason instanceof Error ? reason.message : '알림 등록에 실패했습니다.') }
  }

  const runAccountAction = async (action: () => Promise<void>, fallback: string) => {
    setError(''); setActionMessage('')
    try { await action() } catch (reason) { setError(reason instanceof Error ? reason.message : fallback) }
  }

  const toggleFavorite = async () => {
    if (!token || !report) {
      openAuth('login')
      return
    }
    const saved = favorites.some((game) => game.id === report.game.id)
    await runAccountAction(async () => {
      if (saved) {
        await deleteFavorite(token, report.game.id)
      } else {
        await addFavorite(token, report.game.id)
      }
      setFavorites(await getFavorites(token))
      setActionMessage(saved ? '관심 게임에서 제거했습니다.' : '관심 게임에 추가했습니다.')
    }, '관심 게임을 변경하지 못했습니다.')
  }

  const savePreferences = async (enabled: boolean) => {
    await runAccountAction(async () => {
      const updated = await updatePreferences(token, { ...preferences, emailNotificationsEnabled: enabled })
      setPreferences(updated)
      setActionMessage('알림 설정을 저장했습니다.')
    }, '알림 설정을 저장하지 못했습니다.')
  }

  const runCatalogImport = async (
    apply: boolean,
    appId = adminAppId.trim(),
    gameId = adminGameId.trim(),
  ) => {
    const canonicalGameId = canonicalIdFromTitle(gameId)
    setAdminError('')
    setAdminImporting(true)
    setActionMessage('')
    try {
      const result = adminStore === 'Google Play'
        ? await importGooglePlayCatalogGame(
            appId,
            canonicalGameId,
            apply,
            apply && adminResult?.game.matchDecision?.status === 'NeedsReview',
          )
        : await importSteamCatalogGame(appId, canonicalGameId, apply)
      setAdminGameId(result.game.id)
      setAdminResult(result)
      if (apply && reviewingAppId === appId) {
        try {
          setCatalogSyncJob(await resolveCatalogSyncReview(appId, 'APPROVED'))
          setReviewingAppId('')
        } catch (reason) {
          setAdminError(reason instanceof Error ? `게임은 등록됐지만 검토 상태를 갱신하지 못했습니다: ${reason.message}` : '게임은 등록됐지만 검토 상태를 갱신하지 못했습니다.')
        }
      }
      if (apply) {
        try {
          setCatalogJob(await startCatalogCollection(adminStore))
          setActionMessage(`카탈로그 등록을 완료했고 ${adminStore} 가격 수집을 시작했습니다.`)
        } catch (reason) {
          setAdminError(reason instanceof Error ? `게임은 등록됐지만 가격 수집을 시작하지 못했습니다: ${reason.message}` : '게임은 등록됐지만 가격 수집을 시작하지 못했습니다.')
        }
      } else {
        setActionMessage(`${adminStore} 상품 검증이 완료되었습니다.`)
      }
    } catch (reason) {
      setAdminError(reason instanceof Error ? reason.message : `${adminStore} 상품을 검증하지 못했습니다.`)
    } finally {
      setAdminImporting(false)
    }
  }

  const collectCatalogPrices = async () => {
    setError('')
    try {
      setCatalogJob(await startCatalogCollection(adminStore))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '가격 수집을 시작하지 못했습니다.')
    }
  }

  const synchronizeCatalog = async () => {
    setAdminError('')
    try {
      setCatalogSyncJob(await startCatalogSync(catalogSyncBatchSize))
    } catch (reason) {
      setAdminError(reason instanceof Error ? reason.message : 'Steam 카탈로그 동기화를 시작하지 못했습니다.')
    }
  }

  const inspectCatalogReview = (review: NonNullable<CatalogSyncJob['pendingReviews']>[number]) => {
    const suggestedGameId = canonicalIdFromTitle(review.title)
    setReviewingAppId(review.externalProductId)
    setAdminAppId(review.externalProductId)
    setAdminGameId(suggestedGameId)
    setPendingCandidate({
      store: 'Steam',
      externalProductId: review.externalProductId,
      title: review.title,
      productUrl: `https://store.steampowered.com/app/${review.externalProductId}`,
      platforms: [],
    })
    setAdminResult(null)
    setAdminError(suggestedGameId ? review.reason : `${review.reason}. 영문 게임명 또는 canonical Game ID를 입력해주세요.`)
  }

  const rejectCatalogReview = async (appId: string) => {
    setAdminError('')
    try {
      setCatalogSyncJob(await resolveCatalogSyncReview(appId, 'REJECTED'))
      if (reviewingAppId === appId) {
        setReviewingAppId('')
        setPendingCandidate(null)
      }
      setActionMessage(`Steam App ${appId}를 카탈로그 등록 대상에서 제외했습니다.`)
    } catch (reason) {
      setAdminError(reason instanceof Error ? reason.message : '검토 항목을 제외하지 못했습니다.')
    }
  }

  const searchCatalogCandidates = async () => {
    setAdminSearching(true)
    setError('')
    setAdminError('')
    setAdminResult(null)
    setPendingCandidate(null)
    try {
      setAdminCandidates(await searchStoreCandidates(adminStore, adminQuery.trim()))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Store 상품을 검색하지 못했습니다.')
    } finally {
      setAdminSearching(false)
    }
  }

  const chooseCatalogCandidate = (candidate: StoreProductCandidate) => {
    const suggestedGameId = canonicalIdFromTitle(candidate.title)
    setReviewingAppId('')
    setAdminAppId(candidate.externalProductId)
    setAdminGameId(suggestedGameId)
    setPendingCandidate(candidate)
    setAdminCandidates([])
    setAdminResult(null)
    setAdminError('')
    if (!suggestedGameId) {
      setAdminError('영문 게임명 또는 canonical Game ID를 입력한 뒤 Preview해주세요.')
      return
    }
    void runCatalogImport(false, candidate.externalProductId, suggestedGameId)
  }

  const startSocialLogin = async (provider: OAuthProvider, link = false) => {
    try { window.location.assign(await getOAuthUrl(provider, token, link)) }
    catch (reason) { setError(reason instanceof Error ? reason.message : '소셜 로그인을 시작하지 못했습니다.') }
  }

  const selectGame = async (
    game: GameSummary,
    updateAddress = true,
    platform = '',
  ) => {
    const changingGame = selectedGameId !== '' && selectedGameId !== game.id
    const requestId = ++requestSequence.current
    setLoading(true)
    setError('')
    setSelectedGameId(game.id)
    setSelectedPlatform(platform)
    if (changingGame) {
      setReport(null)
      setHistory(null)
    }
    if (updateAddress) {
      const address = new URL(window.location.href)
      address.searchParams.set('game', game.id)
      if (platform) address.searchParams.set('platform', platform)
      else address.searchParams.delete('platform')
      window.history.replaceState(null, '', address)
    }
    try {
      const [priceReport, priceHistory] = await Promise.all([
        getGamePrices(game.id, platform),
        getGamePriceHistory(game.id, undefined, platform),
      ])
      if (requestId === requestSequence.current) {
        setReport(priceReport)
        const visibleProducts = new Set(
          priceReport.products.map((product) => `${product.store}:${product.productId}`),
        )
        setHistory({
          ...priceHistory,
          histories: priceHistory.histories.filter((item) =>
            visibleProducts.has(`${item.store}:${item.productId}`)),
        })
      }
    } catch (reason) {
      if (requestId === requestSequence.current) {
        setError(reason instanceof Error ? reason.message : '가격을 불러오지 못했습니다.')
      }
    } finally {
      if (requestId === requestSequence.current) setLoading(false)
    }
  }

  const submitSearch = async (event?: FormEvent) => {
    event?.preventDefault()
    const requestId = ++requestSequence.current
    setLoading(true)
    setError('')
    setGames([])
    setSelectedGameId('')
    setSelectedPlatform('')
    setReport(null)
    setHistory(null)
    setShowGameResults(true)
    setBrowseMode(false)
    setSuggestionsOpen(false)
    try {
      const matches = await getGames(query.trim())
      if (requestId !== requestSequence.current) return
      setGames(matches)
      if (matches.length > 0) await selectGame(matches[0])
      if (matches.length === 0) setError('일치하는 게임이 없습니다.')
    } catch (reason) {
      if (requestId === requestSequence.current) {
        setError(reason instanceof Error ? reason.message : '검색에 실패했습니다.')
      }
    } finally {
      if (requestId === requestSequence.current) setLoading(false)
    }
  }

  useEffect(() => {
    void getGames()
      .then((catalogGames) => {
        setGames(catalogGames)
        if (catalogGames.length === 0) {
          setError('등록된 게임이 없습니다.')
          return
        }
        const requestedGameId = new URLSearchParams(window.location.search).get('game')
        const requestedPlatform = new URLSearchParams(window.location.search).get('platform') ?? ''
        const initialGame = catalogGames.find((game) => game.id === requestedGameId)
        if (!initialGame) {
          return
        }
        setShowGameResults(true)
        const initialPlatform = initialGame.platforms.includes(requestedPlatform)
          ? requestedPlatform
          : ''
        void selectGame(
          initialGame,
          requestedPlatform !== initialPlatform,
          initialPlatform,
        )
      })
      .catch((reason) => {
        setError(reason instanceof Error ? reason.message : '게임 목록을 불러오지 못했습니다.')
      })
    void getCollectionRuns()
      .then(setCollectionRuns)
      .catch(() => setCollectionStatusError('수집 상태를 불러오지 못했습니다.'))
    void getCatalogFilters()
      .then((filters) => {
        setCatalogFilters(filters)
        if (selectedStore || browsePlatform || selectedGenre || selectedTag) {
          void browseCatalog({
            store: selectedStore || undefined,
            platform: browsePlatform || undefined,
            genre: selectedGenre || undefined,
            tag: selectedTag || undefined,
            sort: gameSort,
            page: 1,
          })
        }
      })
      .catch(() => setCatalogFilters({ stores: [], platforms: [], genres: [], tags: [] }))
    void getCatalogAdminStatus()
      .then((status) => {
        setCatalogAdminEnabled(status.enabled)
        if (status.enabled) {
          void getCatalogCollectionJob().then(setCatalogJob)
          void getCatalogSyncJob().then(setCatalogSyncJob)
        }
      })
      .catch(() => setCatalogAdminEnabled(false))
    // Load the catalog and initial game once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (catalogJob?.status !== 'RUNNING') {
      return
    }
    const timer = window.setInterval(() => {
      void getCatalogCollectionJob().then((job) => {
        setCatalogJob(job)
        if (job.status === 'SUCCEEDED') {
          setActionMessage('Steam 가격 수집이 완료되었습니다. 새 게임을 바로 검색할 수 있습니다.')
          void getCollectionRuns().then(setCollectionRuns)
        }
      })
    }, 1000)
    return () => window.clearInterval(timer)
  }, [catalogJob?.status])

  useEffect(() => {
    if (catalogSyncJob?.status !== 'RUNNING') {
      return
    }
    const timer = window.setInterval(() => {
      void getCatalogSyncJob().then((job) => {
        setCatalogSyncJob(job)
        if (job.status === 'SUCCEEDED') {
          setActionMessage(`Steam 카탈로그 동기화 완료: 자동 등록 ${job.accepted}개, 검토 대기 ${job.review}개`)
          void getGames().then(setGames)
        }
      })
    }, 1000)
    return () => window.clearInterval(timer)
  }, [catalogSyncJob?.status])

  useEffect(() => {
    const value = query.trim()
    if (value.length === 0) {
      setSuggestions([])
      setSuggestionsOpen(false)
      setActiveSuggestion(-1)
      return
    }
    const requestId = ++suggestionSequence.current
    const timer = window.setTimeout(() => {
      void getGames(value)
        .then((matches) => {
          if (requestId !== suggestionSequence.current) {
            return
          }
          setSuggestions(matches.slice(0, 6))
          setSuggestionsOpen(true)
          setActiveSuggestion(-1)
        })
        .catch(() => {
          if (requestId === suggestionSequence.current) {
            setSuggestions([])
            setSuggestionsOpen(true)
          }
        })
    }, 250)
    return () => window.clearTimeout(timer)
  }, [query])

  useEffect(() => {
    const closeAutocomplete = (event: MouseEvent) => {
      if (!autocompleteRef.current?.contains(event.target as Node)) {
        setSuggestionsOpen(false)
      }
    }
    document.addEventListener('mousedown', closeAutocomplete)
    return () => document.removeEventListener('mousedown', closeAutocomplete)
  }, [])

  useEffect(() => {
    const hash = new URLSearchParams(window.location.hash.slice(1))
    const oauthSuccess = hash.get('oauth') === 'success'
    if (oauthSuccess) localStorage.setItem('game-price-session', '1')
    if (oauthSuccess || hash.has('oauth_linked')) window.history.replaceState(null, '', window.location.pathname + window.location.search)
    if (!token) return
    void refreshAccount(token).catch(() => {
      localStorage.removeItem('game-price-session'); setToken(''); setUser(null)
    })
  }, [token])

  return (
    <div className="app-shell">
      <button className="mobile-menu" aria-label="메뉴 열기" onClick={() => setSidebarOpen(true)}>☰</button>
      {sidebarOpen && <button className="sidebar-backdrop" aria-label="메뉴 닫기" onClick={() => setSidebarOpen(false)} />}
      <aside className={`sidebar ${sidebarOpen ? 'open' : ''}`}>
        <button className="brand" onClick={openGameFinder}>
          <span>CGP</span>
          <strong>CompGamePrice</strong>
        </button>
        <nav aria-label="주 메뉴">
          <button className={activeView === 'games' ? 'active' : ''} onClick={openGameFinder}>게임 찾기</button>
          <button className={activeView === 'favorites' ? 'active' : ''} onClick={() => user ? navigate('favorites') : openAuth('login')}>관심 게임</button>
          <button className={activeView === 'alerts' ? 'active' : ''} onClick={() => user ? navigate('alerts') : openAuth('login')}>가격 알림</button>
          <button className={activeView === 'notifications' ? 'active' : ''} onClick={() => user ? navigate('notifications') : openAuth('login')}>
            알림함 {notifications.filter((item) => !item.read).length > 0 && <span className="nav-count">{notifications.filter((item) => !item.read).length}</span>}
          </button>
          <button className={activeView === 'collection' ? 'active' : ''} onClick={() => navigate('collection')}>수집 상태</button>
          {catalogAdminEnabled && <button className={activeView === 'admin' ? 'active' : ''} onClick={() => navigate('admin')}>카탈로그 관리</button>}
        </nav>
        <div className="sidebar-user">
          {user ? (
            <>
              <span className="avatar">{user.email.slice(0, 1).toUpperCase()}</span>
              <div><strong>{user.email}</strong><button onClick={() => navigate('account')}>계정 설정</button></div>
              <button className="logout-button" onClick={() => void signOut()}>로그아웃</button>
            </>
          ) : (
            <>
              <p>로그인하면 원하는 가격에 알림을 받을 수 있어요.</p>
              <button onClick={() => openAuth('login')}>로그인</button>
              <button className="secondary" onClick={() => openAuth('register')}>회원가입</button>
            </>
          )}
        </div>
      </aside>
      <main className="app-main">
      {error && <p className="notice error">{error}</p>}
      {actionMessage && <p className="notice success">{actionMessage}</p>}
      {activeView === 'games' && <>
      <header className="hero">
        <p className="eyebrow">GAME PRICE TRACKER</p>
        <h1>어디서 사야 가장 저렴할까?</h1>
        <p className="intro">Steam과 모바일 Store 가격을 한눈에 비교해보세요.</p>
        <form onSubmit={submitSearch} className="search-form">
          <div className="autocomplete" ref={autocompleteRef}>
            <input
              aria-label="게임 이름"
              aria-autocomplete="list"
              aria-controls="game-suggestions"
              aria-expanded={suggestionsOpen}
              value={query}
              onChange={(event) => { setQuery(event.target.value); setCatalogRequestMessage('') }}
              onFocus={() => query.trim() && setSuggestionsOpen(true)}
              onKeyDown={handleAutocompleteKeyDown}
              placeholder="게임 이름을 입력하세요"
              role="combobox"
            />
            {suggestionsOpen && <div className="suggestions" id="game-suggestions" role="listbox">
              {suggestions.map((game, index) => <button
                aria-selected={index === activeSuggestion}
                className={index === activeSuggestion ? 'active' : ''}
                key={game.id}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => chooseSuggestion(game)}
                role="option"
                type="button"
              >
                <strong>{game.title}</strong>
                <span>{game.platforms.join(' · ')}</span>
              </button>)}
              {suggestions.length === 0 && <div className="catalog-request"><p>등록된 게임이 없습니다.</p>{catalogRequestMessage ? <span>{catalogRequestMessage}</span> : <button type="button" disabled={catalogRequestSubmitting || query.trim().length < 2} onMouseDown={(event) => event.preventDefault()} onClick={() => void submitCatalogRequest()}>{catalogRequestSubmitting ? '요청 중…' : `“${query.trim()}” 등록 요청`}</button>}</div>}
            </div>}
          </div>
          <button disabled={loading} type="submit">
            {loading ? '조회 중…' : '가격 찾기'}
          </button>
        </form>
        <section className="catalog-discovery" aria-label="게임 카테고리 탐색">
          <div className="quick-platforms" aria-label="빠른 플랫폼 탐색">
            {[
              ['Windows', 'PC'],
              ['Nintendo Switch', 'Switch'],
              ['Nintendo Switch 2', 'Switch 2'],
              ['Android', 'Android'],
              ['iOS', 'iPhone'],
            ].filter(([platform]) => catalogFilters.platforms.includes(platform)).map(([platform, label]) => <button className={browseMode && browsePlatform === platform && !selectedStore && !selectedGenre && !selectedTag ? 'active' : ''} key={platform} type="button" onClick={() => applyQuickPlatform(platform)}>{label}</button>)}
          </div>
          <details className="detailed-filters"><summary>구매처·플랫폼·장르로 자세히 찾기</summary>
            <form onSubmit={applyDetailedFilters}>
              <label>구매처<select aria-label="구매처 필터" value={selectedStore} onChange={(event) => setSelectedStore(event.target.value)}><option value="">전체</option>{catalogFilters.stores.map((store) => <option key={store}>{store}</option>)}</select></label>
              <label>플레이 환경<select aria-label="플랫폼 탐색 필터" value={browsePlatform} onChange={(event) => setBrowsePlatform(event.target.value)}><option value="">전체</option>{catalogFilters.platforms.map((platform) => <option key={platform}>{platform}</option>)}</select></label>
              <label>장르<select aria-label="장르 필터" value={selectedGenre} onChange={(event) => setSelectedGenre(event.target.value)}><option value="">전체</option>{catalogFilters.genres.map((genre) => <option key={genre}>{genre}</option>)}</select></label>
              <label>태그<select aria-label="태그 필터" value={selectedTag} onChange={(event) => setSelectedTag(event.target.value)}><option value="">전체</option>{catalogFilters.tags.map((tag) => <option key={tag}>{tag}</option>)}</select></label>
              <button disabled={loading} type="submit">조건으로 찾기</button>
            </form>
          </details>
        </section>
      </header>

      {showGameResults && selectedGameId && <section className="inline-alert-card">
        <div><strong>{report?.game.title ?? selectedGameId} 가격 알림</strong><span>{selectedPlatform || '모든 플랫폼'}{report?.cheapest ? ` · 현재 ${formatMoney(report.cheapest.price)}` : ''}</span></div>
        <input type="number" min="0" value={targetPrice} onChange={(event) => setTargetPrice(event.target.value)} placeholder="목표 가격(KRW)" />
        {user ? <button onClick={() => void createRule('BelowTargetPrice')}>목표가 알림</button> : <button onClick={() => openAuth('login')}>로그인하고 알림 받기</button>}
      </section>}

      {showGameResults && games.length > 0 && (
        <section className="panel">
          <div className="catalog-heading">
            <h2>{browseMode ? '카테고리 탐색 결과' : query.trim() ? '검색 결과' : '게임 카탈로그'}</h2>
            <span>{browseMode ? `${catalogTotal}개 중 ${games.length}개` : `${games.length}개 게임`}</span>
            {browseMode && <select aria-label="게임 정렬" value={gameSort} onChange={(event) => {
              const sort = event.target.value as GameSort
              setGameSort(sort)
              void browseCatalog({
                store: selectedStore || undefined,
                platform: browsePlatform || undefined,
                genre: selectedGenre || undefined,
                tag: selectedTag || undefined,
                sort,
                page: 1,
              })
            }}><option value="title">이름순</option><option value="lowestPrice">최저가순</option><option value="recentlyUpdated">최근 갱신순</option></select>}
          </div>
          {browseMode && Object.entries(activeBrowseFilters).some(([, value]) => value) && <div className="filter-chips" aria-label="적용된 필터">{Object.entries(activeBrowseFilters).filter(([, value]) => value).map(([name, value]) => <button key={name} type="button" onClick={() => clearBrowseFilter(name as keyof typeof activeBrowseFilters)}>{value} ×</button>)}</div>}
          <div className="game-list">
            {games.map((game) => (
              <button
                className={selectedGameId === game.id ? 'selected' : ''}
                aria-pressed={selectedGameId === game.id}
                disabled={loading && selectedGameId === game.id}
                key={game.id}
                onClick={() => void selectGame(game)}
              >
                <strong>{game.title}</strong>
                <small>{game.platforms.join(' · ')}</small>
                <span>{game.genres.join(' · ') || '장르 정보 수집 중'}</span>
                <em>{game.priceStatus === 'Available' && game.lowestPrice ? `최저 ${formatMoney(game.lowestPrice)}` : game.priceStatus === 'Stale' ? '가격 갱신 필요' : '가격 수집 중'}</em>
              </button>
            ))}
          </div>
          {browseMode && catalogTotal > 12 && <nav className="catalog-pagination" aria-label="게임 목록 페이지"><button type="button" disabled={catalogPage <= 1 || loading} onClick={() => void browseCatalog({ store: selectedStore || undefined, platform: browsePlatform || undefined, genre: selectedGenre || undefined, tag: selectedTag || undefined, sort: gameSort, page: catalogPage - 1 })}>이전</button><span>{catalogPage} / {Math.ceil(catalogTotal / 12)}</span><button type="button" disabled={catalogPage * 12 >= catalogTotal || loading} onClick={() => void browseCatalog({ store: selectedStore || undefined, platform: browsePlatform || undefined, genre: selectedGenre || undefined, tag: selectedTag || undefined, sort: gameSort, page: catalogPage + 1 })}>다음</button></nav>}
        </section>
      )}
      {showGameResults && games.length === 0 && browseMode && <section className="panel empty-catalog-result"><h2>조건에 맞는 게임이 없습니다.</h2><p>필터를 줄이거나 이름으로 검색해보세요.</p></section>}

      {showGameResults && report && (
        <>
        <section className="results">
          <div className="result-heading">
            <div>
              <p className="eyebrow">CURRENT PRICES</p>
              <h2>{report.game.title}</h2>
              <p className="game-platforms">
                플레이 가능: {report.game.platforms.join(' · ')}
              </p>
              {report.game.developers.length > 0 && <p className="game-platforms">개발: {report.game.developers.join(' · ')}</p>}
              {report.game.publishers.length > 0 && <p className="game-platforms">배급: {report.game.publishers.join(' · ')}</p>}
            </div>
            {report.cheapest && (
              <div className="best-summary">
                <span>현재 최저가</span>
                <strong>{formatMoney(report.cheapest.price)}</strong>
                <small>{report.cheapest.store}</small>
              </div>
            )}
            <button className="favorite-button" onClick={() => void toggleFavorite()}>
              {favorites.some((game) => game.id === report.game.id) ? '★ 관심 게임' : '☆ 관심 게임 추가'}
            </button>
          </div>

          <div className="game-summary" aria-label="게임 가격 요약">
            <div><span>비교 Store</span><strong>{report.products.length}곳</strong></div>
            <div><span>역대 최저</span><strong>{report.products.some((product) => product.history) ? formatMoney(report.products.filter((product) => product.history).reduce((lowest, product) => product.history!.lowestPrice.minorAmount < lowest.minorAmount ? product.history!.lowestPrice : lowest, report.products.find((product) => product.history)!.history!.lowestPrice)) : '데이터 없음'}</strong></div>
            <div><span>최대 할인</span><strong>{Math.max(0, ...report.products.map((product) => product.discountPercent))}%</strong></div>
            <div><span>최신 가격</span><strong>{report.products.filter((product) => !product.stale).length}/{report.products.length}</strong></div>
          </div>

          <div className="platform-filter" aria-label="플랫폼 필터">
            <button
              className={selectedPlatform === '' ? 'active' : ''}
              aria-pressed={selectedPlatform === ''}
              onClick={() => void selectGame(report.game, true, '')}
            >
              전체
            </button>
            {report.game.platforms.map((platform) => (
              <button
                className={selectedPlatform === platform ? 'active' : ''}
                aria-pressed={selectedPlatform === platform}
                key={platform}
                onClick={() => void selectGame(report.game, true, platform)}
              >
                {platform}
              </button>
            ))}
          </div>

          <div className="price-grid">
            {report.products.map((product) => {
              const cheapest = report.cheapest?.productId === product.productId
              return (
                <article className={`${cheapest ? 'price-card cheapest' : 'price-card'}${product.stale ? ' stale' : ''}`} key={`${product.store}-${product.productId}`}>
                  <div className="card-topline">
                    <span className="store">{product.store}</span>
                    {cheapest ? <span className="badge">BEST</span> : product.stale && <span className="badge stale-badge">오래된 가격</span>}
                  </div>
                  <p className="offer-meta">
                    {product.region} · {product.edition} · {product.offerType}
                  </p>
                  <strong className="price">{formatMoney(product.price)}</strong>
                  {product.regularPrice && product.discountPercent > 0 && (
                    <div className="discount-summary">
                      <span className="discount-rate">{product.discountPercent}% 할인</span>
                      <del>{formatMoney(product.regularPrice)}</del>
                    </div>
                  )}
                  <p className="platforms">{product.platforms.join(' · ')}</p>
                  <p className="freshness">
                    마지막 정상 확인: {product.lastSuccessfulCheckAt
                      ? new Date(product.lastSuccessfulCheckAt).toLocaleString('ko-KR')
                      : '확인되지 않음'}
                  </p>
                  {product.compatibility.map((entry) => (
                    <p className="platforms" key={entry.platform}>
                      {entry.platform}: {entry.status}
                    </p>
                  ))}
                  <a
                    className="purchase-link"
                    href={product.purchaseUrl}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {product.store}에서 보기
                  </a>
                  <div className="history">
                    <span>역대 최저</span>
                    <strong>{product.history ? formatMoney(product.history.lowestPrice) : '데이터 없음'}</strong>
                  </div>
                  {product.recommendation ? (
                    <div className={`recommendation ${product.recommendation.rating.toLowerCase()}`}>
                      <strong>
                        {recommendationLabel[product.recommendation.rating] ?? product.recommendation.rating}
                      </strong>
                      <span>
                        역대 최저보다 {formatMoney({
                          minorAmount: product.recommendation.amountAboveHistoricalLow,
                          currency: product.price.currency,
                        })} 높음 ({product.recommendation.percentAboveHistoricalLow}%)
                      </span>
                      <ul>
                        {product.recommendation.reasons.map((reason) => (
                          <li key={reason}>{recommendationReason[reason] ?? reason}</li>
                        ))}
                      </ul>
                    </div>
                  ) : (
                    <p className="recommendation pending">
                      {product.stale
                        ? '오래된 가격은 구매 추천에서 제외됩니다.'
                        : '추천 분석을 위한 가격 이력이 없습니다.'}
                    </p>
                  )}
                </article>
              )
            })}
          </div>
          {report.products.length === 0 && (
            <p className="notice empty">아직 수집된 가격이 없습니다.</p>
          )}
        </section>
        {history && <PriceHistoryChart histories={history.histories} />}
        </>
      )}
      </>}

      {activeView === 'favorites' && user && <section className="view-panel">
        <p className="eyebrow">WATCHLIST</p>
        <h1 className="view-title">관심 게임</h1>
        <p className="view-description">자주 확인하는 게임을 모아두고 가격 상세로 바로 이동하세요.</p>
        {favorites.length === 0 && <p className="empty-state">아직 관심 게임이 없습니다.</p>}
        <div className="game-list">{favorites.map((game) => <button key={game.id} onClick={() => { navigate('games'); setShowGameResults(true); setGames([game]); setQuery(game.title); void selectGame(game) }}><strong>{game.title}</strong><small>{game.platforms.join(' · ')}</small></button>)}</div>
      </section>}

      {activeView === 'alerts' && user && <section className="view-panel">
        <p className="eyebrow">PRICE ALERTS</p>
        <h1 className="view-title">내 가격 알림</h1>
        <p className="view-description">게임 상세에서 설정한 목표 가격과 가격 변동 규칙입니다.</p>
        {rules.length === 0 && <p className="empty-state">등록된 가격 알림이 없습니다.</p>}
        {rules.map((rule) => <div className="account-row" key={rule.id}>
          <span><strong>{rule.gameTitle ?? rule.gameId}</strong> · {rule.platform ?? '모든 플랫폼'} · {rule.type}{rule.targetPriceMinor !== undefined ? ` · ₩${rule.targetPriceMinor.toLocaleString()}` : ''}</span>
          <button onClick={() => void runAccountAction(async () => { await deleteAlertRule(token, rule.id); setRules(await getAlertRules(token)); setActionMessage('알림 규칙을 삭제했습니다.') }, '알림 삭제에 실패했습니다.')}>삭제</button>
        </div>)}
      </section>}

      {activeView === 'notifications' && user && <section className="view-panel">
        <p className="eyebrow">NOTIFICATIONS</p>
        <h1 className="view-title">알림함</h1>
        {notifications.length === 0 && <p className="empty-state">새 알림이 없습니다.</p>}
        {notifications.map((item) => <button className={`notification-row ${item.read ? 'read' : ''}`} key={item.id} onClick={() => void runAccountAction(async () => { await markNotificationRead(token, item.id); setNotifications(await getNotifications(token)) }, '읽음 처리에 실패했습니다.')}>
          <strong>{item.gameId} · {item.store}</strong><span>{formatMoney(item.price)} · {item.message}</span>
        </button>)}
      </section>}

      {activeView === 'account' && user && <section className="view-panel">
        <p className="eyebrow">ACCOUNT</p>
        <h1 className="view-title">계정 설정</h1>
        <div className="profile-card"><span className="avatar large">{user.email.slice(0, 1).toUpperCase()}</span><div><strong>{user.email}</strong><p>가격 알림 {rules.length}개 · 읽지 않은 알림 {notifications.filter((item) => !item.read).length}개</p></div></div>
        <div className="preference-card">
          <div><h3>이메일 가격 알림</h3><p>목표 가격 도달 알림을 이메일 발송 대기열에 추가합니다.</p></div>
          <label className="toggle"><input type="checkbox" checked={preferences.emailNotificationsEnabled} onChange={(event) => void savePreferences(event.target.checked)} /><span>{preferences.emailNotificationsEnabled ? '사용' : '사용 안 함'}</span></label>
          <div className="preference-meta"><span>지역 <strong>{preferences.region}</strong></span><span>통화 <strong>{preferences.currency}</strong></span></div>
        </div>
        <div className="social-connections"><h3>연결된 로그인</h3>
          {(['google', 'kakao', 'naver'] as OAuthProvider[]).map((provider) => {
            const label: ExternalIdentity['provider'] = provider === 'google' ? 'Google' : provider === 'kakao' ? 'Kakao' : 'Naver'
            const identity = identities.find((item) => item.provider === label)
            return identity ? <div className="social-identity" key={provider}><span>{label}{identity.email ? ` · ${identity.email}` : ''}</span><button onClick={() => void runAccountAction(async () => { await unlinkExternalIdentity(token, identity.id); setIdentities(await getExternalIdentities(token)) }, '계정 연결 해제에 실패했습니다.')}>연결 해제</button></div>
              : <button className={`social-button ${provider}`} key={provider} onClick={() => void startSocialLogin(provider, true)}>{label} 계정 연결</button>
          })}
        </div>
      </section>}

      {activeView === 'collection' && <section className="view-panel collection-panel" aria-label="최근 가격 수집 상태">
        <p className="eyebrow">COLLECTION STATUS</p>
        <h1 className="view-title">최근 수집 실행</h1>
        {collectionStatusError && <p className="status-message error-text">{collectionStatusError}</p>}
        {!collectionStatusError && collectionRuns.length === 0 && <p className="empty-state">아직 저장된 수집 실행이 없습니다.</p>}
        <div className="collection-run-list">{collectionRuns.map((run) => <article key={run.id} className={`collection-run ${run.status.toLowerCase()}`}>
          <span className="status-dot" /><strong>{run.store}</strong><span>{run.status === 'SUCCEEDED' ? '성공' : run.status === 'FAILED' ? '실패' : '실행 중'}</span>
          <small>성공 {run.productsFound} · 검증 거부 {run.productsRejected} · 실패 {run.productsFailed}{run.retryCount > 0 ? ` · 재시도 ${run.retryCount}` : ''}</small>
          {run.errorMessage && <p>{run.errorMessage}</p>}
        </article>)}</div>
      </section>}

      {activeView === 'admin' && catalogAdminEnabled && <section className="view-panel">
        <p className="eyebrow">LOCAL ADMIN</p>
        <h1 className="view-title">Store 상품 연결</h1>
        <p className="view-description">게임 이름으로 Store를 검색하고 본편 상품이 맞는지 확인한 뒤 등록하세요.</p>
        <article className="catalog-sync-panel">
          <div>
            <h2>Steam 자동 동기화</h2>
            <p>아직 처리하지 않은 상품을 제한된 배치로 검사합니다. 확실한 일반판 본편만 자동 등록됩니다.</p>
          </div>
          <label>한 번에 처리할 수<input type="number" min="1" max="100" value={catalogSyncBatchSize} onChange={(event) => setCatalogSyncBatchSize(Number(event.target.value))} /></label>
          <button disabled={catalogSyncJob?.status === 'RUNNING' || catalogSyncBatchSize < 1 || catalogSyncBatchSize > 100} onClick={() => void synchronizeCatalog()}>{catalogSyncJob?.status === 'RUNNING' ? '동기화 중…' : '다음 배치 동기화'}</button>
          {catalogSyncJob && <div className={`sync-summary ${catalogSyncJob.status.toLowerCase()}`}>
            <strong>{catalogSyncJob.status}</strong>
            <span>자동 등록 {catalogSyncJob.accepted ?? 0} · 검토 {catalogSyncJob.review ?? 0} · 제외 {catalogSyncJob.skipped ?? 0} · 실패 {catalogSyncJob.failed ?? 0}</span>
            {catalogSyncJob.lastAppId && <small>마지막 App ID {catalogSyncJob.lastAppId}</small>}
            {catalogSyncJob.priceCollection && <span>신규 게임 가격 수집 {catalogSyncJob.priceCollection.status}</span>}
            {catalogSyncJob.error && <p>{catalogSyncJob.error}</p>}
          </div>}
          {catalogSyncJob && <div className="sync-queue">
            <div className="queue-tabs"><button className={adminQueueView === 'pending' ? 'active' : ''} onClick={() => setAdminQueueView('pending')}>검토 대기 {catalogSyncJob.pendingReviews?.length ?? 0}</button><button className={adminQueueView === 'history' ? 'active' : ''} onClick={() => setAdminQueueView('history')}>처리 이력</button><button className={adminQueueView === 'requests' ? 'active' : ''} onClick={() => setAdminQueueView('requests')}>사용자 요청</button><button className={adminQueueView === 'runs' ? 'active' : ''} onClick={() => setAdminQueueView('runs')}>실행 기록</button></div>
            {adminQueueView === 'pending' && <div className="sync-reviews">{catalogSyncJob.pendingReviews?.length ? catalogSyncJob.pendingReviews.map((review) => <div key={review.externalProductId}><strong>{review.title || `App ${review.externalProductId}`}</strong><span>{review.reason}</span><a href={`https://store.steampowered.com/app/${review.externalProductId}`} target="_blank" rel="noreferrer">Steam 확인 ↗</a><div className="review-actions"><button onClick={() => inspectCatalogReview(review)}>수동 검토</button><button className="danger" onClick={() => void rejectCatalogReview(review.externalProductId)}>제외</button></div></div>) : <p>검토 대기 항목이 없습니다.</p>}</div>}
            {adminQueueView === 'history' && <div className="sync-reviews">{catalogSyncJob.reviewHistory?.length ? catalogSyncJob.reviewHistory.map((review) => <div key={`${review.externalProductId}-${review.status}`}><strong>{review.title}</strong><span>{review.reason}</span><small className={review.status.toLowerCase()}>{review.status}</small><a href={`https://store.steampowered.com/app/${review.externalProductId}`} target="_blank" rel="noreferrer">Steam 확인 ↗</a></div>) : <p>처리 이력이 없습니다.</p>}</div>}
            {adminQueueView === 'requests' && <div className="sync-reviews">{catalogSyncJob.gameRequests?.length ? catalogSyncJob.gameRequests.map((request) => <div key={`${request.query}-${request.requestedAt}`}><strong>{request.query}</strong><span>요청 {request.requestCount}회</span><small>{request.status}</small><time>{new Date(request.requestedAt).toLocaleString('ko-KR')}</time></div>) : <p>사용자 요청이 없습니다.</p>}</div>}
            {adminQueueView === 'runs' && <div className="sync-reviews">{catalogSyncJob.recentRuns?.length ? catalogSyncJob.recentRuns.map((run) => <div key={run.id}><strong>실행 #{run.id} · {run.status}</strong><span>처리 {run.processed} · 등록 {run.accepted} · 검토 {run.review} · 제외 {run.skipped} · 실패 {run.failed}</span><small>{new Date(run.startedAt).toLocaleString('ko-KR')}</small></div>) : <p>실행 기록이 없습니다.</p>}</div>}
          </div>}
        </article>
        <div className="admin-search">
          <select aria-label="Store" value={adminStore} onChange={(event) => { setAdminStore(event.target.value); setAdminCandidates([]); setPendingCandidate(null); setAdminResult(null) }}><option value="Steam">Steam</option><option value="Google Play">Google Play</option></select>
          <input aria-label="Store 게임 이름" value={adminQuery} onChange={(event) => setAdminQuery(event.target.value)} placeholder="예: Sekiro" />
          <button disabled={!adminQuery.trim() || adminSearching} onClick={() => void searchCatalogCandidates()}>{adminSearching ? '검색 중…' : 'Store 검색'}</button>
        </div>
        {adminCandidates.length > 0 && <div className="candidate-list">{adminCandidates.map((candidate) => <button key={`${candidate.store}:${candidate.externalProductId}`} onClick={() => chooseCatalogCandidate(candidate)}><strong>{candidate.title}</strong><span>{candidate.store} · {candidate.platforms.join(' · ') || '플랫폼 확인 필요'}</span><small>상품 ID {candidate.externalProductId}</small></button>)}</div>}
        {pendingCandidate && !adminResult && <div className="candidate-confirmation">
          <div><strong>{pendingCandidate.title}</strong><span>상품 ID {pendingCandidate.externalProductId}</span></div>
          <label>영문 게임명 또는 Canonical Game ID
            <input value={adminGameId} onChange={(event) => setAdminGameId(event.target.value)} placeholder="예: Ogu and the Secret Forest" />
            {adminGameId.trim() && <small>저장 ID: {canonicalIdFromTitle(adminGameId) || '영문 또는 숫자를 입력해주세요.'}</small>}
          </label>
          <button disabled={!canonicalIdFromTitle(adminGameId) || adminImporting} onClick={() => void runCatalogImport(false)}>{adminImporting ? '확인 중…' : 'Preview'}</button>
          {adminError && <p className="admin-feedback error" role="alert">{adminError}</p>}
        </div>}
        <details className="advanced-admin"><summary>고급 입력: 상품 ID 직접 사용</summary>
        <div className="admin-form">
          <label>{adminStore === 'Google Play' ? 'Google Play Package Name' : 'Steam App ID'}<input value={adminAppId} onChange={(event) => setAdminAppId(event.target.value)} placeholder={adminStore === 'Google Play' ? '예: com.example.game' : '예: 1245620'} inputMode={adminStore === 'Google Play' ? 'text' : 'numeric'} /></label>
          <label>Canonical Game ID (선택)<input value={adminGameId} onChange={(event) => setAdminGameId(event.target.value)} placeholder="한글 제목이면 예: dave-the-diver" /></label>
          <button disabled={!(adminStore === 'Google Play' ? /^[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+$/.test(adminAppId.trim()) : /^\d+$/.test(adminAppId.trim())) || adminImporting} onClick={() => void runCatalogImport(false)}>{adminImporting ? '확인 중…' : 'Preview'}</button>
        </div>
        {adminError && !pendingCandidate && <p className="admin-feedback error" role="alert">{adminError}</p>}
        </details>
        {adminResult && <article className="admin-preview">
          <h2>{adminResult.game.title}</h2>
          <p><strong>ID</strong> {adminResult.game.id}</p>
          <p><strong>플랫폼</strong> {adminResult.game.platforms.join(' · ')}</p>
          <p><strong>{adminStore} 상품 ID</strong> {adminResult.game.matchedProduct?.productId ?? adminAppId}</p>
          {adminResult.game.matchedProduct?.developer && <p><strong>개발사</strong> {adminResult.game.matchedProduct.developer}</p>}
          {adminResult.game.matchedProduct?.priceMinor !== undefined && <p><strong>현재 가격</strong> {adminResult.game.matchedProduct.priceMinor.toLocaleString('ko-KR')} {adminResult.game.matchedProduct.currency}</p>}
          {adminResult.game.matchDecision && <div className={`match-decision ${adminResult.game.matchDecision.status.toLowerCase()}`} role="status"><strong>{adminResult.game.matchDecision.status === 'ApprovedCandidate' ? '연결 가능' : adminResult.game.matchDecision.status === 'NeedsReview' ? '수동 확인 필요' : '연결 불가'}</strong><div className="identity-comparison"><span>Canonical: {adminResult.game.title}<small>{adminResult.game.developers.join(' · ') || '개발사 정보 없음'}</small></span><span>Google Play: {adminResult.game.matchedProduct?.title}<small>{adminResult.game.matchedProduct?.developer || '개발사 정보 없음'}</small></span></div><ul>{adminResult.game.matchDecision.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul></div>}
          {!adminResult.applied && adminResult.game.matchDecision?.status !== 'Rejected' && <button onClick={() => void runCatalogImport(true)}>{adminResult.game.matchDecision?.status === 'NeedsReview' ? '위 경고를 확인하고 등록' : '이 상품을 카탈로그에 등록'}</button>}
          {adminResult.applied && <button disabled={catalogJob?.status === 'RUNNING'} onClick={() => void collectCatalogPrices()}>{catalogJob?.status === 'RUNNING' ? '가격 수집 중…' : `${adminStore} 가격 수집 시작`}</button>}
        </article>}
        {catalogJob && catalogJob.status !== 'IDLE' && <div className={`admin-job ${catalogJob.status.toLowerCase()}`}><strong>{catalogJob.store ?? adminStore} 수집 상태: {catalogJob.status}</strong>{catalogJob.error && <span>{catalogJob.error}</span>}</div>}
      </section>}
    </main>

    {authOpen && <div className="modal-backdrop" role="presentation" onMouseDown={() => setAuthOpen(false)}>
      <section className="auth-modal" role="dialog" aria-modal="true" aria-labelledby="auth-title" onMouseDown={(event) => event.stopPropagation()}>
        <button className="modal-close" aria-label="닫기" onClick={() => setAuthOpen(false)}>×</button>
        <p className="eyebrow">WELCOME</p>
        <h2 id="auth-title">{authMode === 'login' ? '로그인' : '회원가입'}</h2>
        <p>가격이 원하는 수준에 도달하면 놓치지 않고 확인하세요.</p>
        {authError && <p className="auth-feedback error" role="alert">{authError}</p>}
        <form className="auth-form" onSubmit={submitAuth}>
          <input type="email" required disabled={authSubmitting} value={email} onChange={(event) => setEmail(event.target.value)} placeholder="email@example.com" />
          <input type="password" required disabled={authSubmitting} minLength={8} value={password} onChange={(event) => setPassword(event.target.value)} placeholder="8자 이상 비밀번호" />
          <button disabled={authSubmitting} type="submit">{authSubmitting ? '확인 중…' : authMode === 'login' ? '로그인' : '가입하기'}</button>
          <button type="button" className="text-button" disabled={authSubmitting} onClick={() => { setAuthMode(authMode === 'login' ? 'register' : 'login'); setAuthError('') }}>{authMode === 'login' ? '처음이신가요? 회원가입' : '이미 계정이 있나요? 로그인'}</button>
          <div className="social-login">{(['google', 'kakao', 'naver'] as OAuthProvider[]).map((provider) => <button type="button" className={`social-button ${provider}`} key={provider} onClick={() => void startSocialLogin(provider)}>{provider === 'google' ? 'Google' : provider === 'kakao' ? 'Kakao' : 'Naver'}</button>)}</div>
        </form>
      </section>
    </div>}
    </div>
  )
}

export default App
