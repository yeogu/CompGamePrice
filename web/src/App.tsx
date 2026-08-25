import { FormEvent, useEffect, useRef, useState } from 'react'
import { getGamePriceHistory, getGamePrices, searchGames } from './api'
import PriceHistoryChart from './PriceHistoryChart'
import type { GamePriceHistoryResponse, GamePriceResponse, GameSummary, Money } from './types'

const formatMoney = (money: Money) =>
  new Intl.NumberFormat('ko-KR', {
    style: 'currency',
    currency: money.currency,
    maximumFractionDigits: 0,
  }).format(money.minorAmount)

function App() {
  const [query, setQuery] = useState('Stardew Valley')
  const [games, setGames] = useState<GameSummary[]>([])
  const [report, setReport] = useState<GamePriceResponse | null>(null)
  const [history, setHistory] = useState<GamePriceHistoryResponse | null>(null)
  const [selectedGameId, setSelectedGameId] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const requestSequence = useRef(0)

  const selectGame = async (game: GameSummary) => {
    const requestId = ++requestSequence.current
    setLoading(true)
    setError('')
    setSelectedGameId(game.id)
    setReport(null)
    setHistory(null)
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
    if (!query.trim()) return
    const requestId = ++requestSequence.current
    setLoading(true)
    setError('')
    setGames([])
    setSelectedGameId('')
    setReport(null)
    setHistory(null)
    try {
      const matches = await searchGames(query.trim())
      if (requestId !== requestSequence.current) return
      setGames(matches)
      if (matches.length === 1) await selectGame(matches[0])
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
    void submitSearch()
    // Initial example search only.
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

      {games.length > 1 && (
        <section className="panel">
          <h2>검색 결과</h2>
          <div className="game-list">
            {games.map((game) => (
              <button
                className={selectedGameId === game.id ? 'selected' : ''}
                aria-pressed={selectedGameId === game.id}
                disabled={loading && selectedGameId === game.id}
                key={game.id}
                onClick={() => void selectGame(game)}
              >
                {game.title}
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
                  <strong className="price">{formatMoney(product.price)}</strong>
                  {product.regularPrice && product.discountPercent > 0 && (
                    <div className="discount-summary">
                      <span className="discount-rate">{product.discountPercent}% 할인</span>
                      <del>{formatMoney(product.regularPrice)}</del>
                    </div>
                  )}
                  <p className="platforms">{product.platforms.join(' · ')}</p>
                  <div className="history">
                    <span>역대 최저</span>
                    <strong>{product.history ? formatMoney(product.history.lowestPrice) : '데이터 없음'}</strong>
                  </div>
                  <p className="recommendation">
                    {product.recommendation?.rating ?? '분석 대기'}
                  </p>
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
