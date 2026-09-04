export function gameIdFromLocation(location: Location): string {
  const match = location.pathname.match(/^\/games\/([^/]+)\/?$/)
  if (match) {
    return decodeURIComponent(match[1])
  }
  return new URLSearchParams(location.search).get('game') ?? ''
}

export function gameDetailPath(gameId: string, platform = ''): string {
  const parameters = new URLSearchParams()
  if (platform) {
    parameters.set('platform', platform)
  }
  const query = parameters.size > 0 ? `?${parameters}` : ''
  return `/games/${encodeURIComponent(gameId)}${query}`
}
