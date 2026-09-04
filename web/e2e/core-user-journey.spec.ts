import { expect, test } from '@playwright/test'

test('game autocomplete selects a catalog game with the keyboard', async ({ page }) => {
  await page.goto('/')
  const search = page.getByLabel('게임 이름')

  await search.fill('Ha')
  await expect(page.getByRole('option', { name: /Hades/ })).toBeVisible()
  await search.press('ArrowDown')
  await search.press('Enter')

  await expect(page).toHaveURL(/\/games\/hades$/)
  await expect(page.getByRole('heading', { name: 'Hades' }).last()).toBeVisible()
  await expect(page.getByRole('heading', { name: '게임 카탈로그' })).toHaveCount(0)
  await expect(page.getByRole('listbox')).toHaveCount(0)
})

test('game autocomplete reports an empty catalog match', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('게임 이름').fill('not-a-catalog-game')
  await expect(page.getByText('등록된 게임이 없습니다.')).toBeVisible()
  await page.getByLabel('게임 이름').press('Escape')
  await expect(page.getByRole('listbox')).toHaveCount(0)
})

test('user browses games by combined store, platform, and genre filters', async ({ page }) => {
  await page.goto('/')
  await page.getByText('구매처·플랫폼·장르로 자세히 찾기').click()
  await page.getByLabel('구매처 필터').selectOption('Google Play')
  await page.getByLabel('플랫폼 탐색 필터').selectOption('Android')
  await page.getByLabel('장르 필터').selectOption('Simulation')
  await page.getByLabel('태그 필터').selectOption('Farming')
  await page.getByRole('button', { name: '조건으로 찾기' }).click()

  await expect(page.getByRole('heading', { name: '카테고리 탐색 결과' })).toBeVisible()
  await expect(page.getByRole('button', { name: /Stardew Valley/ })).toBeVisible()
  await expect(page.getByRole('button', { name: /Hades/ })).toHaveCount(0)
  await expect(page.getByText('Simulation · RPG')).toBeVisible()
  await expect(page).toHaveURL(/store=Google\+Play/)
  await expect(page).toHaveURL(/browsePlatform=Android/)
  await expect(page.getByLabel('적용된 필터').getByRole('button', { name: 'Farming ×' })).toBeVisible()
})

test('quick platform discovery distinguishes Nintendo Switch 2', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('빠른 플랫폼 탐색').getByRole('button', { name: 'Switch 2' }).click()

  await expect(page.getByRole('heading', { name: '카테고리 탐색 결과' })).toBeVisible()
  await expect(page.getByRole('button', { name: /Hades/ })).toBeVisible()
  await expect(page.getByRole('button', { name: /Stardew Valley/ })).toHaveCount(0)
})

test('platform filtering preserves the current scroll position', async ({ page }) => {
  await page.goto('/games/stardew-valley')
  const platformFilter = page.getByLabel('플랫폼 필터')
  await expect(platformFilter).toBeVisible()
  await platformFilter.scrollIntoViewIfNeeded()
  const before = await page.evaluate(() => window.scrollY)

  await platformFilter.getByRole('button', { name: 'Linux', exact: true }).click()
  await expect(page).toHaveURL(/platform=Linux/)
  await expect(platformFilter.getByRole('button', { name: 'Linux', exact: true })).toHaveAttribute('aria-pressed', 'true')
  const after = await page.evaluate(() => window.scrollY)

  expect(Math.abs(after - before)).toBeLessThan(40)
})

test('catalog selection opens a dedicated detail page and restores the list', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('빠른 플랫폼 탐색').getByRole('button', { name: 'Switch 2' }).click()
  const catalogHeading = page.getByRole('heading', { name: '카테고리 탐색 결과' })
  await expect(catalogHeading).toBeVisible()
  await page.getByRole('button', { name: /Hades/ }).click()

  await expect(page).toHaveURL(/\/games\/hades$/)
  await expect(catalogHeading).toHaveCount(0)
  await expect(page.getByRole('button', { name: /게임 목록으로/ }).first()).toBeVisible()
  await page.getByRole('button', { name: /게임 목록으로/ }).first().click()

  await expect(page).toHaveURL(/browsePlatform=Nintendo\+Switch\+2/)
  await expect(catalogHeading).toBeVisible()
  await expect(page.getByLabel('빠른 플랫폼 탐색').getByRole('button', { name: 'Switch 2' })).toHaveClass(/active/)
})

test('unknown game detail shows a recoverable not-found state', async ({ page }) => {
  await page.goto('/games/not-a-real-game')

  await expect(page.getByRole('heading', { name: '게임 정보를 표시할 수 없습니다.' })).toBeVisible()
  await expect(page.getByText('존재하지 않는 게임입니다.')).toBeVisible()
  await expect(page.getByRole('button', { name: '게임 목록으로 돌아가기' })).toBeVisible()
})

test('login failure stays visible in the authentication dialog', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: '로그인', exact: true }).click()
  await page.getByPlaceholder('email@example.com').fill('missing-user@example.com')
  await page.getByPlaceholder('8자 이상 비밀번호').fill('wrong-password')
  await page.getByRole('button', { name: '로그인', exact: true }).last().click()

  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  await expect(dialog.getByRole('alert')).toHaveText(
    '이메일 또는 비밀번호가 올바르지 않습니다.',
  )
})

test('authentication dialog offers email login only', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: '로그인', exact: true }).click()

  const dialog = page.getByRole('dialog')
  await expect(dialog.getByPlaceholder('email@example.com')).toBeVisible()
  await expect(dialog.getByPlaceholder('8자 이상 비밀번호')).toBeVisible()
  await expect(dialog.getByRole('button', { name: 'Google' })).toHaveCount(0)
  await expect(dialog.getByRole('button', { name: 'Kakao' })).toHaveCount(0)
  await expect(dialog.getByRole('button', { name: 'Naver' })).toHaveCount(0)
})

test('user can open the password reset request form', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: '로그인', exact: true }).click()
  await page.getByRole('button', { name: '비밀번호를 잊으셨나요?' }).click()

  const dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('heading', { name: '비밀번호 찾기' })).toBeVisible()
  await expect(dialog.getByPlaceholder('email@example.com')).toBeVisible()
  await expect(dialog.getByRole('button', { name: '재설정 메일 보내기' })).toBeVisible()
})

test('password reset link opens the new password form', async ({ page }) => {
  await page.goto(`/?resetToken=${'a'.repeat(64)}`)

  const dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('heading', { name: '새 비밀번호 설정' })).toBeVisible()
  await expect(dialog.getByPlaceholder('새 비밀번호 (8자 이상)')).toBeVisible()
  await expect(dialog.getByPlaceholder('새 비밀번호 확인')).toBeVisible()
  await expect(dialog.getByRole('button', { name: '비밀번호 변경' })).toBeVisible()
})

test('user can search, inspect prices, create an alert, and log out', async ({ page }) => {
  await page.goto('/')

  await expect(page.getByRole('heading', { name: '게임 카탈로그' })).toHaveCount(0)
  await expect(page.getByText('PRICE HISTORY')).toHaveCount(0)

  await page.getByLabel('게임 이름').fill('Hades')
  await page.getByRole('button', { name: '가격 찾기' }).click()
  await page.getByRole('button', { name: /Hades/ }).click()
  await expect(page).toHaveURL(/\/games\/hades$/)
  await expect(page.getByRole('heading', { name: 'Hades' }).last()).toBeVisible()
  await expect(page.getByText('플레이 가능:')).toContainText('Nintendo Switch 2')
  await expect(page.getByText('Epic Games Store').first()).toBeVisible()
  await expect(page.getByText('PRICE HISTORY')).toBeVisible()

  await page.getByRole('button', { name: '회원가입', exact: true }).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await page.getByPlaceholder('email@example.com').fill('browser-flow@example.com')
  await page.getByPlaceholder('8자 이상 비밀번호').fill('browser-password-123')
  await page.getByRole('button', { name: '가입하기' }).click()
  await expect(page.getByText('browser-flow@example.com').first()).toBeVisible()

  await page.getByPlaceholder('목표 가격(KRW)').fill('20000')
  await page.getByRole('button', { name: '목표가 알림' }).click()
  await expect(page.getByText('알림 규칙을 등록했습니다.')).toBeVisible()
  await page.getByRole('button', { name: '가격 알림', exact: true }).click()
  await expect(page.getByText(/Hades · 모든 플랫폼 · BelowTargetPrice · ₩20,000/)).toBeVisible()

  await page.getByRole('button', { name: '로그아웃' }).click()
  await expect(page.getByRole('button', { name: '로그인', exact: true })).toBeVisible()
})
