import { useEffect, useMemo, useRef, useState } from 'react'
import type { PointerEvent } from 'react'
import type { Money, PriceObservation, ProductPriceHistory } from './types'
import { storeAccentColor } from './VisualBadges'

const formatMoney = (money: Money) => {
  const zeroDecimalCurrency = money.currency === 'KRW' || money.currency === 'JPY'
  const amount = zeroDecimalCurrency ? money.minorAmount : money.minorAmount / 100
  return new Intl.NumberFormat('ko-KR', {
    style: 'currency',
    currency: money.currency,
    maximumFractionDigits: zeroDecimalCurrency ? 0 : 2,
  }).format(amount)
}

const formatDate = (value: string) =>
  new Intl.DateTimeFormat('ko-KR', { dateStyle: 'medium', timeStyle: 'short' })
    .format(new Date(value))

interface Props { histories: ProductPriceHistory[] }
type DisplayObservation = PriceObservation & { originalPrice?: Money }
interface ChartPoint { x: number; y: number; observation: DisplayObservation }
interface TooltipState { store: string; observation: DisplayObservation; left: number; top: number }

const dailyObservations = (history: ProductPriceHistory) => {
  const byDate = new Map<string, ProductPriceHistory['observations'][number]>()
  for (const observation of history.observations) {
    byDate.set(observation.observedAt.slice(0, 10), observation)
  }
  const daily = [...byDate.entries()]
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([date, observation]) => ({ date, observation }))
  return daily.filter((item, index) => {
    if (index === 0) return true
    const previous = daily[index - 1].observation
    return previous.price.minorAmount !== item.observation.price.minorAmount ||
      previous.price.currency !== item.observation.price.currency ||
      previous.purchasable !== item.observation.purchasable
  })
}

function PointShape({ point, store, onPointer, onLeave }: {
  point: ChartPoint
  store: string
  onPointer: (event: PointerEvent<SVGElement>, store: string, observation: DisplayObservation) => void
  onLeave: () => void
}) {
  const color = storeAccentColor(store)
  const events = {
    onPointerEnter: (event: PointerEvent<SVGElement>) => onPointer(event, store, point.observation),
    onPointerMove: (event: PointerEvent<SVGElement>) => onPointer(event, store, point.observation),
    onPointerDown: (event: PointerEvent<SVGElement>) => onPointer(event, store, point.observation),
    onPointerLeave: onLeave,
  }
  return <circle {...events} className="trend-point" cx={point.x} cy={point.y} r="7" stroke={color} />
}

function PriceHistoryChart({ histories }: Props) {
  const available = useMemo(
    () => histories.filter((history) => history.observations.length > 0),
    [histories],
  )
  const hasConvertedForeignPrices = available.some((history) =>
    history.observations.some((item) => item.price.currency !== 'KRW' && item.krwConversion),
  )
  const comparable = useMemo(
    () => available.map((history) => ({
      ...history,
      observations: history.observations.flatMap((item) => {
        if (item.price.currency === 'KRW') return [item]
        if (!item.krwConversion) return []
        return [{ ...item, originalPrice: item.price, price: item.krwConversion.price }]
      }),
    })).filter((history) => history.observations.length > 0),
    [available],
  )
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

  const showTooltip = (event: PointerEvent<SVGElement>, store: string, observation: DisplayObservation) => {
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
        <div className="store-legend" aria-label="표시할 Store 선택">
          {comparable.map((history) => {
            const color = storeAccentColor(history.store)
            const active = !hiddenStores.has(history.store)
            return (
              <button aria-pressed={active} className={active ? 'active' : ''} key={history.store} onClick={() => toggleStore(history.store)}>
                <span className="legend-shape" style={{ borderColor: color, backgroundColor: active ? color : 'transparent' }} />
                {history.store}
              </button>
            )
          })}
        </div>
      </div>

      {hasConvertedForeignPrices && <p className="data-note">외화 가격은 ECB의 관측일 기준환율로 원화 환산했습니다. 휴일에는 직전 영업일 환율을 사용하며 실제 카드 결제액과 다를 수 있습니다.</p>}

      {chart ? (
        <>
          <div className="chart-wrap" ref={chartWrapRef}>
            <div className="chart-labels">
              <span>최고 {formatMoney({ minorAmount: chart.high, currency: 'KRW' })}</span>
              <span>최저 {formatMoney({ minorAmount: chart.low, currency: 'KRW' })}</span>
            </div>
            <svg aria-label="Store별 가격 추이 비교" role="img" viewBox={`0 0 ${chart.width} ${chart.height}`}>
              <line className="grid-line" x1="30" x2="610" y1="30" y2="30" />
              <line className="grid-line" x1="30" x2="610" y1="210" y2="210" />
              {chart.series.map((series) => {
                const color = storeAccentColor(series.store)
                return (
                  <g aria-label={series.store} key={series.store}>
                    {series.points.length > 1 && <polyline className="trend-line" points={series.points.map((point) => `${point.x},${point.y}`).join(' ')} stroke={color} />}
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
                <span style={{ color: storeAccentColor(tooltip.store) }}>
                  {tooltip.store}
                </span>
                <strong>{formatMoney(tooltip.observation.price)}</strong>
                {tooltip.observation.originalPrice && <small>원가격 {formatMoney(tooltip.observation.originalPrice)}</small>}
                {tooltip.observation.krwConversion && tooltip.observation.originalPrice && (
                  <small>1 {tooltip.observation.originalPrice.currency} = ₩{tooltip.observation.krwConversion.rate.toLocaleString('ko-KR', { maximumFractionDigits: 2 })} · {tooltip.observation.krwConversion.rateDate} {tooltip.observation.krwConversion.source}</small>
                )}
                {tooltip.observation.regularPrice && tooltip.observation.discountPercent > 0 && (
                  <small>
                    {tooltip.observation.discountPercent}% 할인 · 정상가{' '}
                    {formatMoney(tooltip.observation.regularPrice)}
                  </small>
                )}
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
              const color = storeAccentColor(series.store)
              return (
                <div key={series.store}>
                  <span><i style={{ backgroundColor: color }} />{series.store}</span>
                  <time dateTime={latest.observedAt}>{formatDate(latest.observedAt)}</time>
                  <strong>
                    {formatMoney(latest.price)}
                    {latest.discountPercent > 0 && (
                      <small className="latest-discount">-{latest.discountPercent}%</small>
                    )}
                  </strong>
                </div>
              )
            })}
          </div>
        </>
      ) : comparable.length === 0
        ? <p className="notice">원화로 비교할 수 있는 가격 데이터가 없습니다. 환율 동기화 상태를 확인하세요.</p>
        : <p className="notice">범례에서 하나 이상의 Store를 선택하세요.</p>}
    </section>
  )
}

export default PriceHistoryChart
