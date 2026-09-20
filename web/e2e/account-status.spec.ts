import { expect, test } from '@playwright/test'

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('game-price-session', '1'))
})

test('failed session verification does not promise a retained login', async ({ page }) => {
  await page.route('**/api/auth/me', route => route.fulfill({ status: 503, json: { error: 'Unavailable' } }))
  await page.goto('/')
  await expect(page.getByText('계정 정보를 불러오지 못했습니다. 연결 상태를 확인한 뒤 새로고침해주세요.')).toBeVisible()
  await expect(page.getByText(/로그인 상태는 유지됩니다/)).toHaveCount(0)
})

test('a failed ancillary request does not hide a verified user', async ({ page }) => {
  await page.route('**/api/auth/me', route => route.fulfill({ json: { id: 1, email: 'verified@example.com', role: 'MEMBER' } }))
  await page.route('**/api/alert-rules', route => route.fulfill({ status: 503, json: { error: 'Unavailable' } }))
  await page.goto('/')
  await expect(page.getByRole('button', { name: '로그아웃', exact: true })).toBeVisible()
  await expect(page.getByText(/로그인 상태는 유지됩니다/)).toHaveCount(0)
})

test('expired sessions explicitly request login again', async ({ page }) => {
  await page.route('**/api/auth/me', route => route.fulfill({ status: 401, json: { error: 'Unauthorized' } }))
  await page.goto('/')
  await expect(page.getByText('로그인 세션이 만료되었거나 유효하지 않습니다. 다시 로그인해주세요.')).toBeVisible()
  await expect(page.getByRole('button', { name: '로그아웃', exact: true })).toHaveCount(0)
})
