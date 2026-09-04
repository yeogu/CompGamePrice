import type { ReactNode } from 'react'

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
}

export function GameDetailView({ children, error, loading, onBack }: GameDetailViewProps) {
  return (
    <div className="game-detail-view">
      <nav className="detail-navigation" aria-label="게임 상세 탐색">
        <button type="button" aria-label="게임 목록으로" onClick={onBack}>← 게임 목록으로</button>
      </nav>
      {loading && <section className="detail-state" role="status"><h1>게임 정보를 불러오는 중입니다.</h1></section>}
      {!loading && error && <section className="detail-state error" role="alert"><h1>게임 정보를 표시할 수 없습니다.</h1><p>{error}</p><button type="button" onClick={onBack}>게임 목록으로 돌아가기</button></section>}
      {!loading && !error && children}
    </div>
  )
}
