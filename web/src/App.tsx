import { FormEvent, useEffect, useRef, useState } from 'react'
import { getCollectionRuns, getGamePriceHistory, getGamePrices, getGames } from './api'
import PriceHistoryChart from './PriceHistoryChart'
import type { CollectionRun, GamePriceHistoryResponse, GamePriceResponse, GameSummary, Money } from './types'

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
  const [collectionRuns, setCollectionRuns] = useState<CollectionRun[]>([])
  const [collectionStatusError, setCollectionStatusError] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const requestSequence = useRef(0)

  const selectGame = async (game: GameSummary, updateAddress = true) => {
    const requestId = ++requestSequence.current
    setLoading(true)
    setError('')
    setSelectedGameId(game.id)
    setReport(null)
    setHistory(null)
    if (updateAddress) {
      const address = new URL(window.location.href)
      address.searchParams.set('game', game.id)
      window.history.replaceState(null, '', address)
    }
    try {
      const [priceReport, priceHistory] = await Promise.all([
        getGamePrices(game.id),
        getGamePriceHistory(game.id),
      ])
      if (requestId === requestSequence.current) {
        setReport(priceReport)
        setHistory(priceHistory)
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
        const initialGame = catalogGames.find((game) => game.id === requestedGameId)
          ?? catalogGames[0]
        void selectGame(initialGame, requestedGameId !== initialGame.id)
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

      {error && <p className="notice error">{error}</p>}

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
