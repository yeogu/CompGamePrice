import { expect, test } from '@playwright/test'

test('user can search, inspect prices, create an alert, and log out', async ({ page }) => {
  await page.goto('/')

  await page.getByLabel('게임 이름').fill('Hades')
  await page.getByRole('button', { name: '가격 찾기' }).click()
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
