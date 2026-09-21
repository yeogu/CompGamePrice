import { ArrowLeft, Check, Share2 } from 'lucide-react'
import { useEffect, useRef, useState, type ReactNode } from 'react'

interface GameCatalogViewProps {
  children: ReactNode
}

export function GameCatalogView({ children }: GameCatalogViewProps) {
  return <div className="game-catalog-view">{children}</div>
}

interface GameDetailViewProps {
  children: ReactNode
  error: string
  loading: boolean
  onBack: () => void
  title?: string
}

export function GameDetailView({ children, error, loading, onBack, title = '' }: GameDetailViewProps) {
  const viewRef = useRef<HTMLDivElement>(null)
  const [compactHeader, setCompactHeader] = useState(false)
  const [linkCopied, setLinkCopied] = useState(false)

  useEffect(() => {
    setCompactHeader(false)
    const heading = viewRef.current?.querySelector('.game-identity h2')
    if (!heading || !window.matchMedia('(max-width: 600px)').matches) return
    const observer = new IntersectionObserver(([entry]) => {
      setCompactHeader(!entry.isIntersecting && entry.boundingClientRect.top < 0)
    }, { threshold: 0.01 })
    observer.observe(heading)
    return () => observer.disconnect()
  }, [title, loading, error])

  useEffect(() => {
    if (!linkCopied) return
    const timer = window.setTimeout(() => setLinkCopied(false), 1800)
    return () => window.clearTimeout(timer)
  }, [linkCopied])

  const share = async () => {
    const url = window.location.href
    try {
      if (navigator.share) {
        await navigator.share({ title: title ? `${title} | DealQuest` : 'DealQuest', url })
        return
      }
      await navigator.clipboard.writeText(url)
      setLinkCopied(true)
    } catch (reason) {
      if (!(reason instanceof DOMException && reason.name === 'AbortError')) {
        setLinkCopied(false)
      }
    }
  }

  return (
    <div className="game-detail-view" ref={viewRef}>
      <nav className={`mobile-detail-topbar${compactHeader ? ' compact' : ''}`} aria-label="모바일 게임 상세 탐색">
        <button type="button" aria-label="게임 목록으로" onClick={onBack}><ArrowLeft /></button>
        <strong aria-hidden={!compactHeader}>{title}</strong>
        <button type="button" aria-label={linkCopied ? '링크 복사됨' : '게임 공유'} onClick={() => void share()}>
          {linkCopied ? <Check /> : <Share2 />}
        </button>
      </nav>
      <nav className="detail-navigation" aria-label="게임 상세 탐색">
        <button type="button" aria-label="게임 목록으로" onClick={onBack}>← 게임 목록으로</button>
      </nav>
      {loading && <section className="detail-state" role="status"><h1>게임 정보를 불러오는 중입니다.</h1></section>}
      {!loading && error && <section className="detail-state error" role="alert"><h1>게임 정보를 표시할 수 없습니다.</h1><p>{error}</p><button type="button" onClick={onBack}>게임 목록으로 돌아가기</button></section>}
      {!loading && !error && children}
    </div>
  )
}
