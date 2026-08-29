import { FormEvent, KeyboardEvent, useEffect, useRef, useState } from 'react'
import { addAlertRule, addFavorite, deleteAlertRule, deleteFavorite, getAlertRules, getCollectionRuns, getExternalIdentities, getFavorites, getGamePriceHistory, getGamePrices, getGames, getMe, getNotifications, getOAuthUrl, getPreferences, login, logout, markNotificationRead, register, unlinkExternalIdentity, updatePreferences } from './api'
import PriceHistoryChart from './PriceHistoryChart'
import type { AlertRule, AlertRuleType, CollectionRun, ExternalIdentity, GamePriceHistoryResponse, GamePriceResponse, GameSummary, Money, Notification, OAuthProvider, User, UserPreferences } from './types'

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

type AppView = 'games' | 'favorites' | 'alerts' | 'notifications' | 'account' | 'collection'

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
    const address = new URL(window.location.href)
    address.searchParams.delete('game')
    address.searchParams.delete('platform')
    window.history.replaceState(null, '', address)
  }

  const chooseSuggestion = (game: GameSummary) => {
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
    // Load the catalog and initial game once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

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
              onChange={(event) => setQuery(event.target.value)}
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
              {suggestions.length === 0 && <p>등록된 게임이 없습니다.</p>}
            </div>}
          </div>
          <button disabled={loading} type="submit">
            {loading ? '조회 중…' : '가격 찾기'}
          </button>
        </form>
      </header>

      {showGameResults && selectedGameId && <section className="inline-alert-card">
        <div><strong>{report?.game.title ?? selectedGameId} 가격 알림</strong><span>{selectedPlatform || '모든 플랫폼'}{report?.cheapest ? ` · 현재 ${formatMoney(report.cheapest.price)}` : ''}</span></div>
        <input type="number" min="0" value={targetPrice} onChange={(event) => setTargetPrice(event.target.value)} placeholder="목표 가격(KRW)" />
        {user ? <button onClick={() => void createRule('BelowTargetPrice')}>목표가 알림</button> : <button onClick={() => openAuth('login')}>로그인하고 알림 받기</button>}
      </section>}

      {showGameResults && games.length > 0 && (
        <section className="panel">
          <div className="catalog-heading">
            <h2>{query.trim() ? '검색 결과' : '게임 카탈로그'}</h2>
            <span>{games.length}개 게임</span>
          </div>
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
              </button>
            ))}
          </div>
        </section>
      )}

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
