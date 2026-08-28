import { FormEvent, useEffect, useRef, useState } from 'react'
import { addAlertRule, deleteAlertRule, getAlertRules, getCollectionRuns, getExternalIdentities, getGamePriceHistory, getGamePrices, getGames, getMe, getNotifications, getOAuthUrl, login, logout, markNotificationRead, register, unlinkExternalIdentity } from './api'
import PriceHistoryChart from './PriceHistoryChart'
import type { AlertRule, AlertRuleType, CollectionRun, ExternalIdentity, GamePriceHistoryResponse, GamePriceResponse, GameSummary, Money, Notification, OAuthProvider, User } from './types'

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
  const [actionMessage, setActionMessage] = useState('')

  const refreshAccount = async (activeToken: string) => {
    const [me, nextRules, nextNotifications, nextIdentities] = await Promise.all([
      getMe(activeToken), getAlertRules(activeToken), getNotifications(activeToken), getExternalIdentities(activeToken),
    ])
    setUser({ ...me, email: nextIdentities[0]?.email ?? me.email }); setRules(nextRules); setNotifications(nextNotifications); setIdentities(nextIdentities)
  }

  const submitAuth = async (event: FormEvent) => {
    event.preventDefault(); setError('')
    try {
      const result = authMode === 'register' ? await register(email, password) : await login(email, password)
      localStorage.setItem('game-price-session', '1'); setToken('cookie'); setUser(result.user)
      setPassword(''); await refreshAccount('cookie')
    } catch (reason) { setError(reason instanceof Error ? reason.message : '인증에 실패했습니다.') }
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

  const startSocialLogin = async (provider: OAuthProvider, link = false) => {
    try { window.location.assign(await getOAuthUrl(provider, token, link)) }
    catch (reason) { setError(reason instanceof Error ? reason.message : '소셜 로그인을 시작하지 못했습니다.') }
  }

  const selectGame = async (
    game: GameSummary,
    updateAddress = true,
    platform = '',
  ) => {
    const requestId = ++requestSequence.current
    setLoading(true)
    setError('')
    setSelectedGameId(game.id)
    setSelectedPlatform(platform)
    setReport(null)
    setHistory(null)
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
          ?? catalogGames[0]
        const initialPlatform = initialGame.platforms.includes(requestedPlatform)
          ? requestedPlatform
          : ''
        void selectGame(
          initialGame,
          requestedGameId !== initialGame.id || requestedPlatform !== initialPlatform,
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
    <main>
      <header className="hero">
        <p className="eyebrow">GAME PRICE TRACKER</p>
        <h1>어디서 사야 가장 저렴할까?</h1>
        <p className="intro">Steam과 모바일 Store 가격을 한눈에 비교해보세요.</p>
        <form onSubmit={submitSearch} className="search-form">
          <input
            aria-label="게임 이름"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="게임 이름을 입력하세요"
          />
          <button disabled={loading} type="submit">
            {loading ? '조회 중…' : '가격 찾기'}
          </button>
        </form>
      </header>

      <section className="account-panel">
        {user ? (
          <>
            <div className="account-heading"><div><p className="eyebrow">MY ALERTS</p><h2>{user.email}</h2></div>
              <button onClick={() => void logout(token).finally(() => { localStorage.removeItem('game-price-session'); setToken(''); setUser(null); setRules([]); setNotifications([]); setIdentities([]) })}>로그아웃</button>
            </div>
            {selectedGameId && <div className="alert-controls">
              <strong>{report?.game.title ?? selectedGameId} · {selectedPlatform || '모든 플랫폼'}</strong>
              <button onClick={() => void createRule('PriceDrop')}>가격 하락 알림</button>
              <button onClick={() => void createRule('NewHistoricalLow')}>새 역대 최저가</button>
              <button onClick={() => void createRule('BelowAverage')}>평균가 이하</button>
              <input type="number" min="0" value={targetPrice} onChange={(event) => setTargetPrice(event.target.value)} placeholder="목표 가격(KRW)" />
              <button onClick={() => void createRule('BelowTargetPrice')}>목표가 알림</button>
            </div>}
            <div className="account-grid">
              <div><h3>알림 규칙</h3>{rules.length === 0 && <p>등록된 규칙이 없습니다.</p>}{rules.map((rule) => <div className="account-row" key={rule.id}><span>{rule.gameTitle ?? rule.gameId} · {rule.platform ?? '모든 플랫폼'} · {rule.type}{rule.targetPriceMinor !== undefined ? ` · ₩${rule.targetPriceMinor.toLocaleString()}` : ''}</span><button onClick={() => void runAccountAction(async () => { await deleteAlertRule(token, rule.id); setRules(await getAlertRules(token)); setActionMessage('알림 규칙을 삭제했습니다.') }, '알림 삭제에 실패했습니다.')}>삭제</button></div>)}</div>
              <div><h3>알림함</h3>{notifications.length === 0 && <p>새 알림이 없습니다.</p>}{notifications.map((item) => <button className={`notification-row ${item.read ? 'read' : ''}`} key={item.id} onClick={() => void runAccountAction(async () => { await markNotificationRead(token, item.id); setNotifications(await getNotifications(token)) }, '읽음 처리에 실패했습니다.')}><strong>{item.gameId} · {item.store}</strong><span>{formatMoney(item.price)} · {item.message}</span></button>)}</div>
            </div>
            <div className="social-connections"><h3>연결된 로그인</h3>
              {(['google', 'kakao', 'naver'] as OAuthProvider[]).map((provider) => {
                const label: ExternalIdentity['provider'] = provider === 'google' ? 'Google' : provider === 'kakao' ? 'Kakao' : 'Naver'
                const identity = identities.find((item) => item.provider === label)
                return identity ? <div className="social-identity" key={provider}><span>{label}{identity.email ? ` · ${identity.email}` : ''}</span><button onClick={() => void runAccountAction(async () => { await unlinkExternalIdentity(token, identity.id); setIdentities(await getExternalIdentities(token)) }, '계정 연결 해제에 실패했습니다.')}>연결 해제</button></div>
                  : <button className={`social-button ${provider}`} key={provider} onClick={() => void startSocialLogin(provider, true)}>{label} 계정 연결</button>
              })}
            </div>
          </>
        ) : (
          <form className="auth-form" onSubmit={submitAuth}>
            <div><p className="eyebrow">PRICE ALERTS</p><h2>{authMode === 'login' ? '로그인' : '회원가입'}</h2></div>
            <input type="email" required value={email} onChange={(event) => setEmail(event.target.value)} placeholder="email@example.com" />
            <input type="password" required minLength={8} value={password} onChange={(event) => setPassword(event.target.value)} placeholder="8자 이상 비밀번호" />
            <button type="submit">{authMode === 'login' ? '로그인' : '가입하기'}</button>
            <button type="button" className="text-button" onClick={() => setAuthMode(authMode === 'login' ? 'register' : 'login')}>{authMode === 'login' ? '처음이신가요? 회원가입' : '이미 계정이 있나요? 로그인'}</button>
            <div className="social-login"><span>또는 소셜 계정으로 계속</span>{(['google', 'kakao', 'naver'] as OAuthProvider[]).map((provider) => <button type="button" className={`social-button ${provider}`} key={provider} onClick={() => void startSocialLogin(provider)}>{provider === 'google' ? 'Google' : provider === 'kakao' ? 'Kakao' : 'Naver'}</button>)}</div>
          </form>
        )}
      </section>

      {error && <p className="notice error">{error}</p>}
      {actionMessage && <p className="notice success">{actionMessage}</p>}

      <section className="collection-panel" aria-label="최근 가격 수집 상태">
        <div className="collection-heading">
          <div>
            <p className="eyebrow">COLLECTION STATUS</p>
            <h2>최근 수집 실행</h2>
          </div>
          {collectionRuns[0] && (
            <time dateTime={collectionRuns[0].startedAt}>
              {new Intl.DateTimeFormat('ko-KR', {
                dateStyle: 'medium', timeStyle: 'short',
              }).format(new Date(collectionRuns[0].startedAt))}
            </time>
          )}
        </div>
        {collectionStatusError && <p className="status-message error-text">{collectionStatusError}</p>}
        {!collectionStatusError && collectionRuns.length === 0 && (
          <p className="status-message">아직 저장된 수집 실행이 없습니다.</p>
        )}
        <div className="collection-run-list">
          {collectionRuns.map((run) => (
            <article key={run.id} className={`collection-run ${run.status.toLowerCase()}`}>
              <span className="status-dot" />
              <strong>{run.store}</strong>
              <span>{run.status === 'SUCCEEDED' ? '성공' : run.status === 'FAILED' ? '실패' : '실행 중'}</span>
              <small>{run.productsFound}개 상품</small>
              {run.errorMessage && <p>{run.errorMessage}</p>}
            </article>
          ))}
        </div>
      </section>

      {games.length > 0 && (
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

      {report && (
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
                <article className={cheapest ? 'price-card cheapest' : 'price-card'} key={`${product.store}-${product.productId}`}>
                  <div className="card-topline">
                    <span className="store">{product.store}</span>
                    {cheapest && <span className="badge">BEST</span>}
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
                    <p className="recommendation pending">추천 분석을 위한 가격 이력이 없습니다.</p>
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
    </main>
  )
}

export default App
