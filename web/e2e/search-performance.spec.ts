import { expect, test } from '@playwright/test'

test('search loads only twelve initial games and six autocomplete suggestions', async ({ page }) => {
  const initial = page.waitForRequest(request => new URL(request.url()).pathname === '/api/games')
  await page.goto('/')
  expect(new URL((await initial).url()).searchParams.get('pageSize')).toBe('12')
  const suggestion = page.waitForRequest(request => new URL(request.url()).searchParams.get('query') === 'Ha')
  await page.getByLabel('게임 이름').fill('Ha')
  expect(new URL((await suggestion).url()).searchParams.get('pageSize')).toBe('6')
  await expect(page.getByRole('option', { name: /Hades/ })).toBeVisible()
})

test('clearing search aborts the old autocomplete request without showing an error', async ({ page }) => {
  let release: () => void = () => {}
  const pending = new Promise<void>(resolve => { release = resolve })
  await page.route('**/api/games?**', async route => {
    if (new URL(route.request().url()).searchParams.get('query') !== 'slow-candidate') {
      await route.continue()
      return
    }
    await pending
    await route.fulfill({ json: { games: [], page: 1, pageSize: 6, total: 0 } }).catch(() => {})
  })
  await page.goto('/')
  const started = page.waitForRequest(request => new URL(request.url()).searchParams.get('query') === 'slow-candidate')
  await page.getByLabel('게임 이름').fill('slow-candidate')
  await started
  const aborted = page.waitForEvent('requestfailed', request => new URL(request.url()).searchParams.get('query') === 'slow-candidate')
  await page.getByLabel('게임 이름').fill('')
  await aborted
  release()
  await expect(page.getByRole('listbox')).toHaveCount(0)
  await expect(page.getByText(/AbortError|aborted|검색에 실패/)).toHaveCount(0)
})

test('detail artwork loads eagerly without altering the original image URL', async ({ page }) => {
  await page.goto('/games/hades')
  const artwork = page.locator('.result-heading .game-artwork img')
  await expect(artwork).toHaveAttribute('loading', 'eager')
  await expect(artwork).toHaveAttribute('fetchpriority', 'high')
})
