import { Gamepad2 } from 'lucide-react'
import { useState } from 'react'

interface GameArtworkProps {
  imageUrl?: string
  title: string
  compact?: boolean
}

export default function GameArtwork({ imageUrl, title, compact = false }: GameArtworkProps) {
  const [failed, setFailed] = useState(false)
  const showImage = Boolean(imageUrl) && !failed

  return (
    <span className={`game-artwork ${compact ? 'compact' : ''}`} aria-label={`${title} 대표 이미지`}>
      {showImage
        ? <img alt="" loading="lazy" src={imageUrl} onError={() => setFailed(true)} />
        : <Gamepad2 aria-hidden="true" />}
    </span>
  )
}
