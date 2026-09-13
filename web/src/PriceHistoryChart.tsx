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
type PriceChangeKind = 'INITIAL' | 'STORE_PRICE' | 'EXCHANGE_RATE_ONLY'
type DisplayObservation = PriceObservation & {
  originalPrice?: Money
  priceChangeKind?: PriceChangeKind
}
type DisplayProductHistory = Omit<ProductPriceHistory, 'observations'> & {
  observations: DisplayObservation[]
}
interface ChartPoint { x: number; y: number; observation: DisplayObservation }
interface TooltipState { store: string; observation: DisplayObservation; left: number; top: number }

const dailyObservations = (history: DisplayProductHistory) => {
  const byDate = new Map<string, DisplayObservation>()
  for (const observation of history.observations) {
    byDate.set(observation.observedAt.slice(0, 10), observation)
  }
  const daily = [...byDate.entries()]
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([date, observation]) => ({ date, observation }))
  return daily.filter((item, index) => {
    if (index === 0 || index === daily.length - 1) return true
    if (item.observation.priceChangeKind === 'STORE_PRICE') return true
    if (item.observation.priceChangeKind === 'EXCHANGE_RATE_ONLY') return false
    const previous = daily[index - 1].observation
    return previous.price.minorAmount !== item.observation.price.minorAmount ||
      previous.price.currency !== item.observation.price.currency ||
      previous.purchasable !== item.observation.purchasable
  })
}

const comparableHistory = (history: ProductPriceHistory): DisplayProductHistory => {
  let previous: PriceObservation | undefined
  const observations = history.observations.flatMap((item): DisplayObservation[] => {
    const sourcePriceChanged = previous !== undefined && (
      previous.price.minorAmount !== item.price.minorAmount ||
      previous.price.currency !== item.price.currency ||
      previous.discountPercent !== item.discountPercent ||
      previous.purchasable !== item.purchasable
    )
    const priceChangeKind: PriceChangeKind = previous === undefined
      ? 'INITIAL'
      : sourcePriceChanged ? 'STORE_PRICE' : 'EXCHANGE_RATE_ONLY'
    previous = item
    if (item.price.currency === 'KRW') return [{ ...item, priceChangeKind }]
    if (!item.krwConversion) return []
    return [{
      ...item,
      originalPrice: item.price,
      price: item.krwConversion.price,
      priceChangeKind,
    }]
  })
  return { ...history, observations }
}

const daysBetween = (later: string, earlier: string) => Math.max(0, Math.floor(
  (new Date(`${later.slice(0, 10)}T00:00:00Z`).getTime() -
    new Date(`${earlier.slice(0, 10)}T00:00:00Z`).getTime()) / 86_400_000,
))

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
  return <circle {...events} className="trend-point" cx={point.x} cy={point.y} r="4.5" stroke={color} />
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
    () => available.map(comparableHistory)
      .filter((history) => history.observations.length > 0),
    [available],
  )
  const staleExchangeRateDays = useMemo(() => Math.max(0, ...available.flatMap((history) =>
    history.observations.flatMap((item) => item.price.currency !== 'KRW' && item.krwConversion
      ? [daysBetween(item.observedAt, item.krwConversion.rateDate)]
      : []),
  )), [available])
  const trendable = useMemo(
    () => comparable.filter((history) => history.observations.length >= 2),
    [comparable],
  )
  const [hiddenStores, setHiddenStores] = useState<Set<string>>(new Set())
  const [tooltip, setTooltip] = useState<TooltipState | null>(null)
  const chartWrapRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    setHiddenStores((current) => new Set(
      [...current].filter((store) => trendable.some((history) => history.store === store)),
    ))
  }, [trendable])

  const visible = trendable.filter((history) => !hiddenStores.has(history.store))
  const chart = useMemo(() => {
    const dailySeries = visible.map((history) => ({
      ...history,
      daily: dailyObservations(history),
    }))
    const observations = dailySeries.flatMap((history) => history.daily)
    if (observations.length === 0) return null
    const amounts = observations.map((item) => item.observation.price.minorAmount)
    const times = observations.map((item) => new Date(`${item.date}T00:00:00Z`).getTime())
    const observedLow = Math.min(...amounts)
    const observedHigh = Math.max(...amounts)
    const flatRangePadding = Math.max(500, Math.round(observedHigh * 0.05))
    const low = observedLow === observedHigh
      ? Math.max(0, observedLow - flatRangePadding)
      : observedLow
    const high = observedLow === observedHigh
      ? observedHigh + flatRangePadding
      : observedHigh
    const firstTime = Math.min(...times)
    const lastTime = Math.max(...times)
    const width = 760
    const height = 220
    const leftPadding = 72
    const rightPadding = 22
    const topPadding = 20
    const bottomPadding = 28
    const priceRange = Math.max(high - low, 1)
    const timeRange = Math.max(lastTime - firstTime, 1)
    const plotWidth = width - leftPadding - rightPadding
    const plotHeight = height - topPadding - bottomPadding
    const series = dailySeries.map((history) => ({
      ...history,
      points: history.daily.map((item) => ({
        x: firstTime === lastTime ? leftPadding + plotWidth / 2 : leftPadding + ((new Date(`${item.date}T00:00:00Z`).getTime() - firstTime) * plotWidth) / timeRange,
        y: height - bottomPadding - ((item.observation.price.minorAmount - low) * plotHeight) / priceRange,
        observation: item.observation,
      })),
    }))
    const ticks = [high, Math.round((high + low) / 2), low].map((amount) => ({
      amount,
      y: height - bottomPadding - ((amount - low) * plotHeight) / priceRange,
    }))
    return { low, high, firstTime, lastTime, width, height, leftPadding, rightPadding, series, ticks }
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
    const tooltipWidth = Math.min(270, Math.max(180, bounds.width - 24))
    const pointerLeft = event.clientX - bounds.left
    const preferredLeft = pointerLeft + 14
    const left = Math.max(12, Math.min(preferredLeft, bounds.width - tooltipWidth - 12))
    setTooltip({
      store,
      observation,
      left,
      top: event.clientY - bounds.top + 14,
    })
  }

  return (
    <section className="trend-panel">
      <div className="trend-heading">
        <div className="store-legend" aria-label="표시할 Store 선택">
          {trendable.map((history) => {
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
      {staleExchangeRateDays > 4 && <p className="data-note exchange-warning">일부 가격에는 관측일보다 {staleExchangeRateDays}일 오래된 환율이 적용됐습니다. 관리자 화면에서 환율 동기화 상태를 확인하세요.</p>}

      {chart ? (
        <>
          <div className="chart-wrap" ref={chartWrapRef}>
            <svg aria-label="Store별 가격 추이 비교" role="img" viewBox={`0 0 ${chart.width} ${chart.height}`}>
              {chart.ticks.map((tick) => <g key={tick.amount}>
                <text className="axis-price" x="0" y={tick.y + 4}>{formatMoney({ minorAmount: tick.amount, currency: 'KRW' })}</text>
                <line className="grid-line" x1={chart.leftPadding} x2={chart.width - chart.rightPadding} y1={tick.y} y2={tick.y} />
              </g>)}
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
                  <>
                    <small className={`price-change-kind ${tooltip.observation.priceChangeKind === 'STORE_PRICE' ? 'store-price-change' : ''}`}>
                      {tooltip.observation.priceChangeKind === 'STORE_PRICE'
                        ? 'Store 원가격 변경'
                        : tooltip.observation.priceChangeKind === 'EXCHANGE_RATE_ONLY'
                          ? '원가격 동일 · 환율 변동 반영'
                          : '첫 가격 관측'}
                    </small>
                    <small>1 {tooltip.observation.originalPrice.currency} = ₩{tooltip.observation.krwConversion.rate.toLocaleString('ko-KR', { maximumFractionDigits: 2 })} · {tooltip.observation.krwConversion.rateDate} {tooltip.observation.krwConversion.source}</small>
                  </>
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

        </>
      ) : trendable.length === 0
        ? <div className="chart-empty-state"><strong>아직 가격 추이를 그릴 수 없습니다.</strong><span>같은 Store에서 서로 다른 날짜의 가격이 두 번 이상 수집되면 그래프가 표시됩니다.</span></div>
        : <p className="notice">범례에서 하나 이상의 Store를 선택하세요.</p>}

      <div className="current-price-heading">
        <strong>현재 비교 가격</strong>
        <span>모두 원화 기준</span>
      </div>
      <div className="latest-price-list">
            {comparable.map((series) => {
              const latest = series.observations[series.observations.length - 1]
              const color = storeAccentColor(series.store)
              const hasTrend = series.observations.length >= 2
              return (
                <div key={series.store}>
                  <span><i style={{ backgroundColor: color }} />{series.store}</span>
                  <time dateTime={latest.observedAt}>{formatDate(latest.observedAt)}</time>
                  <strong>
                    {formatMoney(latest.price)}
                    {latest.originalPrice && <small className="latest-original">{formatMoney(latest.originalPrice)}</small>}
                    {latest.discountPercent > 0 && (
                      <small className="latest-discount">-{latest.discountPercent}%</small>
                    )}
                  </strong>
                  {!hasTrend && <small className="trend-insufficient">추이 데이터 부족</small>}
                </div>
              )
            })}
      </div>
    </section>
  )
}

export default PriceHistoryChart
