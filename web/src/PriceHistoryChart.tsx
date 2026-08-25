import { useEffect, useMemo, useRef, useState } from 'react'
import type { PointerEvent } from 'react'
import type { Money, PriceObservation, ProductPriceHistory } from './types'

const storeStyles: Record<string, { color: string; dash?: string; shape: 'circle' | 'square' | 'triangle' }> = {
  Steam: { color: '#66c0f4', shape: 'circle' },
  'Google Play': { color: '#73e2a7', dash: '10 7', shape: 'square' },
  'Apple App Store': { color: '#f4a261', dash: '3 7', shape: 'triangle' },
}

const fallbackStyle = { color: '#c7a6ff', dash: '14 5', shape: 'circle' as const }

const formatMoney = (money: Money) =>
  new Intl.NumberFormat('ko-KR', {
    style: 'currency', currency: money.currency, maximumFractionDigits: 0,
  }).format(money.minorAmount)

const formatDate = (value: string) =>
  new Intl.DateTimeFormat('ko-KR', { dateStyle: 'medium', timeStyle: 'short' })
    .format(new Date(value))

interface Props { histories: ProductPriceHistory[] }
interface ChartPoint { x: number; y: number; observation: PriceObservation }
interface TooltipState { store: string; observation: PriceObservation; left: number; top: number }

const dailyObservations = (history: ProductPriceHistory) => {
  const byDate = new Map<string, ProductPriceHistory['observations'][number]>()
  for (const observation of history.observations) {
    byDate.set(observation.observedAt.slice(0, 10), observation)
  }
  return [...byDate.entries()]
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([date, observation]) => ({ date, observation }))
}

function PointShape({ point, store, onPointer, onLeave }: {
  point: ChartPoint
  store: string
  onPointer: (event: PointerEvent<SVGElement>, store: string, observation: PriceObservation) => void
  onLeave: () => void
}) {
  const style = storeStyles[store] ?? fallbackStyle
  const events = {
    onPointerEnter: (event: PointerEvent<SVGElement>) => onPointer(event, store, point.observation),
    onPointerMove: (event: PointerEvent<SVGElement>) => onPointer(event, store, point.observation),
    onPointerDown: (event: PointerEvent<SVGElement>) => onPointer(event, store, point.observation),
    onPointerLeave: onLeave,
  }
  if (style.shape === 'square') {
    return <rect {...events} className="trend-point" height="14" width="14" x={point.x - 7} y={point.y - 7} stroke={style.color} />
  }
  if (style.shape === 'triangle') {
    return <polygon {...events} className="trend-point" points={`${point.x},${point.y - 9} ${point.x - 9},${point.y + 8} ${point.x + 9},${point.y + 8}`} stroke={style.color} />
  }
  return <circle {...events} className="trend-point" cx={point.x} cy={point.y} r="7" stroke={style.color} />
}

function PriceHistoryChart({ histories }: Props) {
  const available = useMemo(
    () => histories.filter((history) => history.observations.length > 0),
    [histories],
  )
  const primaryCurrency = available[0]?.observations[0].price.currency
  const comparable = useMemo(
    () => available.filter((history) =>
      history.observations.every((item) => item.price.currency === primaryCurrency)),
    [available, primaryCurrency],
  )
  const excludedCount = available.length - comparable.length
  const [hiddenStores, setHiddenStores] = useState<Set<string>>(new Set())
  const [tooltip, setTooltip] = useState<TooltipState | null>(null)
  const chartWrapRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    setHiddenStores((current) => new Set(
      [...current].filter((store) => comparable.some((history) => history.store === store)),
    ))
  }, [comparable])

  const visible = comparable.filter((history) => !hiddenStores.has(history.store))
  const chart = useMemo(() => {
    const dailySeries = visible.map((history) => ({
      ...history,
      daily: dailyObservations(history),
    }))
    const observations = dailySeries.flatMap((history) => history.daily)
    if (observations.length === 0) return null
    const amounts = observations.map((item) => item.observation.price.minorAmount)
    const times = observations.map((item) => new Date(`${item.date}T00:00:00Z`).getTime())
    const low = Math.min(...amounts)
    const high = Math.max(...amounts)
    const firstTime = Math.min(...times)
    const lastTime = Math.max(...times)
    const width = 640
    const height = 240
    const padding = 30
    const priceRange = Math.max(high - low, 1)
    const timeRange = Math.max(lastTime - firstTime, 1)
    const series = dailySeries.map((history) => ({
      ...history,
      points: history.daily.map((item) => ({
        x: firstTime === lastTime ? width / 2 : padding + ((new Date(`${item.date}T00:00:00Z`).getTime() - firstTime) * (width - padding * 2)) / timeRange,
        y: high === low ? height / 2 : height - padding - ((item.observation.price.minorAmount - low) * (height - padding * 2)) / priceRange,
        observation: item.observation,
      })),
    }))
    return { low, high, firstTime, lastTime, width, height, series }
  }, [visible])

  if (available.length === 0) {
    return <p className="notice">아직 저장된 가격 관측값이 없습니다.</p>
  }

  const toggleStore = (store: string) => {
    setTooltip(null)
    setHiddenStores((current) => {
      const next = new Set(current)
      if (next.has(store)) next.delete(store)
      else next.add(store)
      return next
    })
  }

  const showTooltip = (event: PointerEvent<SVGElement>, store: string, observation: PriceObservation) => {
    const bounds = chartWrapRef.current?.getBoundingClientRect()
    if (!bounds) return
    setTooltip({
      store,
      observation,
      left: event.clientX - bounds.left + 14,
      top: event.clientY - bounds.top + 14,
    })
  }

  return (
    <section className="trend-panel">
      <div className="trend-heading">
        <div>
          <p className="eyebrow">PRICE HISTORY</p>
          <h2>Store 가격 추이 비교</h2>
        </div>
        <div className="store-legend" aria-label="표시할 Store 선택">
          {comparable.map((history) => {
            const style = storeStyles[history.store] ?? fallbackStyle
            const active = !hiddenStores.has(history.store)
            return (
              <button aria-pressed={active} className={active ? 'active' : ''} key={history.store} onClick={() => toggleStore(history.store)}>
                <span className={`legend-shape ${style.shape}`} style={{ borderColor: style.color, backgroundColor: active ? style.color : 'transparent' }} />
                {history.store}
              </button>
            )
          })}
        </div>
      </div>

      {excludedCount > 0 && <p className="data-note">통화가 다른 {excludedCount}개 Store는 같은 축에서 제외했습니다.</p>}

      {chart ? (
        <>
          <div className="chart-wrap" ref={chartWrapRef}>
            <div className="chart-labels">
              <span>최고 {formatMoney({ minorAmount: chart.high, currency: primaryCurrency! })}</span>
              <span>최저 {formatMoney({ minorAmount: chart.low, currency: primaryCurrency! })}</span>
            </div>
            <svg aria-label="Store별 가격 추이 비교" role="img" viewBox={`0 0 ${chart.width} ${chart.height}`}>
              <line className="grid-line" x1="30" x2="610" y1="30" y2="30" />
              <line className="grid-line" x1="30" x2="610" y1="210" y2="210" />
              {chart.series.map((series) => {
                const style = storeStyles[series.store] ?? fallbackStyle
                return (
                  <g aria-label={series.store} key={series.store}>
                    {series.points.length > 1 && <polyline className="trend-line" points={series.points.map((point) => `${point.x},${point.y}`).join(' ')} stroke={style.color} strokeDasharray={style.dash} />}
                    {series.points.map((point, index) => (
                      <PointShape
                        key={`${series.store}-${index}`}
                        onLeave={() => setTooltip(null)}
                        onPointer={showTooltip}
                        point={point}
                        store={series.store}
                      />
                    ))}
                  </g>
                )
              })}
            </svg>
            {tooltip && (
              <div className="chart-tooltip" role="status" style={{ left: tooltip.left, top: tooltip.top }}>
                <span>{tooltip.store}</span>
                <strong>{formatMoney(tooltip.observation.price)}</strong>
                <time>{formatDate(tooltip.observation.observedAt)}</time>
              </div>
            )}
            <div className="date-axis">
              <time>{formatDate(new Date(chart.firstTime).toISOString())}</time>
              <time>{formatDate(new Date(chart.lastTime).toISOString())}</time>
            </div>
          </div>

          {chart.series.every((series) => series.points.length < 2) && <p className="data-note">각 Store가 하루치 관측값을 가지고 있습니다. 다음 날짜의 가격부터 선으로 연결됩니다.</p>}
          <div className="latest-price-list">
            {chart.series.map((series) => {
              const latest = series.observations[series.observations.length - 1]
              const style = storeStyles[series.store] ?? fallbackStyle
              return (
                <div key={series.store}>
                  <span><i style={{ backgroundColor: style.color }} />{series.store}</span>
                  <time dateTime={latest.observedAt}>{formatDate(latest.observedAt)}</time>
                  <strong>{formatMoney(latest.price)}</strong>
                </div>
              )
            })}
          </div>
        </>
      ) : <p className="notice">범례에서 하나 이상의 Store를 선택하세요.</p>}
    </section>
  )
}

export default PriceHistoryChart
