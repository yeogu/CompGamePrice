import { FormEvent, useEffect, useState } from 'react'
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
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const selectGame = async (game: GameSummary) => {
    setLoading(true)
    setError('')
    try {
      const [priceReport, priceHistory] = await Promise.all([
        getGamePrices(game.id),
        getGamePriceHistory(game.id),
      ])
      setReport(priceReport)
      setHistory(priceHistory)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '가격을 불러오지 못했습니다.')
    } finally {
      setLoading(false)
    }
  }

  const submitSearch = async (event?: FormEvent) => {
    event?.preventDefault()
    if (!query.trim()) return
    setLoading(true)
    setError('')
    setReport(null)
    setHistory(null)
    try {
      const matches = await searchGames(query.trim())
      setGames(matches)
      if (matches.length === 1) await selectGame(matches[0])
      if (matches.length === 0) setError('일치하는 게임이 없습니다.')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '검색에 실패했습니다.')
    } finally {
      setLoading(false)
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

      {!report && games.length > 1 && (
        <section className="panel">
          <h2>검색 결과</h2>
          <div className="game-list">
            {games.map((game) => (
              <button key={game.id} onClick={() => void selectGame(game)}>
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
        </section>
        {history && <PriceHistoryChart histories={history.histories} />}
        </>
      )}
    </main>
  )
}

export default App
