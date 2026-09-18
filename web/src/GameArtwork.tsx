import { Gamepad2 } from 'lucide-react'
import { useEffect, useState } from 'react'

interface GameArtworkProps {
  imageUrl?: string
  title: string
  compact?: boolean
  priority?: boolean
}

export default function GameArtwork({ imageUrl, title, compact = false, priority = false }: GameArtworkProps) {
  const [failed, setFailed] = useState(false)
  const showImage = Boolean(imageUrl) && !failed

  useEffect(() => {
    setFailed(false)
  }, [imageUrl])

  return (
    <span className={`game-artwork ${compact ? 'compact' : ''}`} aria-label={`${title} 대표 이미지`}>
      {showImage
        ? <img alt="" decoding="async" loading={priority ? 'eager' : 'lazy'} fetchPriority={priority ? 'high' : 'auto'} src={imageUrl} onError={() => setFailed(true)} />
        : <Gamepad2 aria-hidden="true" />}
    </span>
  )
}
