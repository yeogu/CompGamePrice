import { useEffect, useMemo, useState } from 'react'
import type { Money, ProductPriceHistory } from './types'

const formatMoney = (money: Money) =>
  new Intl.NumberFormat('ko-KR', {
    style: 'currency',
    currency: money.currency,
    maximumFractionDigits: 0,
  }).format(money.minorAmount)

const formatDate = (value: string) =>
  new Intl.DateTimeFormat('ko-KR', { dateStyle: 'medium', timeStyle: 'short' })
    .format(new Date(value))

interface Props {
  histories: ProductPriceHistory[]
}

function PriceHistoryChart({ histories }: Props) {
  const available = useMemo(
    () => histories.filter((history) => history.observations.length > 0),
    [histories],
  )
  const [selectedStore, setSelectedStore] = useState(available[0]?.store ?? '')

  useEffect(() => {
    if (!available.some((history) => history.store === selectedStore)) {
      setSelectedStore(available[0]?.store ?? '')
    }
  }, [available, selectedStore])

  const selected = available.find((history) => history.store === selectedStore)
  const chart = useMemo(() => {
    if (!selected) return null
    const amounts = selected.observations.map((item) => item.price.minorAmount)
    const low = Math.min(...amounts)
    const high = Math.max(...amounts)
    const width = 640
    const height = 220
    const padding = 28
    const range = Math.max(high - low, 1)
    const points = amounts.map((amount, index) => ({
      x: amounts.length === 1
        ? width / 2
        : padding + (index * (width - padding * 2)) / (amounts.length - 1),
      y: height - padding - ((amount - low) * (height - padding * 2)) / range,
    }))
    return { low, high, width, height, points }
  }, [selected])

  if (!selected || !chart) {
    return <p className="notice">아직 저장된 가격 관측값이 없습니다.</p>
  }

  return (
    <section className="trend-panel">
      <div className="trend-heading">
        <div>
          <p className="eyebrow">PRICE HISTORY</p>
          <h2>가격 추이</h2>
        </div>
        <div className="store-tabs" aria-label="Store 선택">
          {available.map((history) => (
            <button
              className={history.store === selected.store ? 'active' : ''}
              key={history.store}
              onClick={() => setSelectedStore(history.store)}
            >
              {history.store}
            </button>
          ))}
        </div>
      </div>

      <div className="chart-wrap">
        <div className="chart-labels">
          <span>최고 {formatMoney({ minorAmount: chart.high, currency: selected.observations[0].price.currency })}</span>
          <span>최저 {formatMoney({ minorAmount: chart.low, currency: selected.observations[0].price.currency })}</span>
        </div>
        <svg
          aria-label={`${selected.store} 가격 추이`}
          role="img"
          viewBox={`0 0 ${chart.width} ${chart.height}`}
        >
          <line className="grid-line" x1="28" x2="612" y1="28" y2="28" />
          <line className="grid-line" x1="28" x2="612" y1="192" y2="192" />
          {chart.points.length > 1 && (
            <polyline
              className="trend-line"
              points={chart.points.map((point) => `${point.x},${point.y}`).join(' ')}
            />
          )}
          {chart.points.map((point, index) => (
            <circle className="trend-point" cx={point.x} cy={point.y} key={index} r="6" />
          ))}
        </svg>
      </div>

      {selected.observations.length < 2 && (
        <p className="data-note">가격이 한 번 관측되었습니다. 다음 가격 변화부터 선으로 연결됩니다.</p>
      )}
      <div className="observation-list">
        {selected.observations.slice().reverse().map((observation) => (
          <div key={observation.observedAt}>
            <time dateTime={observation.observedAt}>{formatDate(observation.observedAt)}</time>
            <strong>{formatMoney(observation.price)}</strong>
          </div>
        ))}
      </div>
    </section>
  )
}

export default PriceHistoryChart
