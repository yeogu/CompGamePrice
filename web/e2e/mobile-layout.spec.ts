import { expect, test, type Page } from '@playwright/test'

const expectNoPageOverflow = async (page: Page) => {
  const dimensions = await page.evaluate(() => ({
    viewport: document.documentElement.clientWidth,
    document: document.documentElement.scrollWidth,
    body: document.body.scrollWidth,
  }))
  expect(dimensions.document).toBeLessThanOrEqual(dimensions.viewport)
  expect(dimensions.body).toBeLessThanOrEqual(dimensions.viewport)
}

for (const width of [360, 390, 430]) {
  test.describe(`mobile portrait ${width}px`, () => {
    test.use({ viewport: { width, height: 844 } })

    test('catalog filters remain separated inside horizontal rails', async ({ page }) => {
      await page.goto('/')
      await expect(page.getByRole('navigation', { name: '모바일 주 메뉴' })).toBeVisible()
      await expect(page.getByRole('button', { name: '메뉴 열기' })).toHaveCount(0)
      const groups = page.locator('.catalog-filter-options')
      await expect(groups).toHaveCount(2)
      await expect(groups.first().locator('button').nth(1)).toBeVisible()
      await expect(page.getByText(/옆으로 밀어 구매처 더 보기/)).toBeVisible()
      for (let index = 0; index < await groups.count(); index += 1) {
        const overlap = await groups.nth(index).locator('button').evaluateAll((buttons) => {
          const boxes = buttons.map((button) => button.getBoundingClientRect())
          return boxes.some((box, buttonIndex) => boxes.slice(buttonIndex + 1).some((other) =>
            box.left < other.right && box.right > other.left &&
            box.top < other.bottom && box.bottom > other.top,
          ))
        })
        expect(overlap).toBe(false)
      }
      await expectNoPageOverflow(page)
    })

    test('home discovery rails stay inside the page viewport', async ({ page }) => {
      await page.goto('/')
      const discovery = page.getByLabel('홈 게임 추천')
      await expect(discovery).toBeVisible()
      await expect(discovery.getByRole('heading', { name: '오늘의 특가' })).toBeVisible()
      await expect(discovery.getByRole('heading', { name: '역대 최저가' })).toBeVisible()
      await expect(discovery.getByRole('heading', { name: '최근 추가된 게임' })).toBeVisible()
      await expectNoPageOverflow(page)
    })

    test('bottom navigation opens search and account without covering content', async ({ page }) => {
      await page.goto('/')
      const navigation = page.getByRole('navigation', { name: '모바일 주 메뉴' })
      await navigation.getByRole('button', { name: '검색' }).click()
      await expect(page.getByRole('combobox', { name: '게임 이름' })).toBeFocused()
      await navigation.getByRole('button', { name: '마이' }).click()
      await expect(page.getByRole('dialog')).toBeVisible()
      const navBox = await navigation.boundingBox()
      expect(navBox).not.toBeNull()
      expect(navBox!.y + navBox!.height).toBeLessThanOrEqual(844)
      await expectNoPageOverflow(page)
    })

    test('game detail artwork, chart, and cards stay within the viewport', async ({ page }) => {
      await page.goto('/games/hades')
      await expect(page.getByRole('heading', { name: 'Hades' }).last()).toBeVisible()
      for (const selector of ['.result-heading > .game-artwork', '.price-card', '.trend-panel']) {
        const overflowCount = await page.locator(selector).evaluateAll((elements) => elements.filter((element) => {
          const box = element.getBoundingClientRect()
          return box.left < 0 || box.right > document.documentElement.clientWidth
        }).length)
        expect(overflowCount).toBe(0)
      }
      await expect(page.locator('.result-heading > .game-artwork')).toHaveCSS('aspect-ratio', '16 / 9')
      await expectNoPageOverflow(page)
    })

    test('login dialog fits while mobile keyboard reduces the viewport', async ({ page }) => {
      await page.goto('/')
      await page.getByRole('button', { name: '로그인', exact: true }).click()
      await page.setViewportSize({ width, height: 520 })
      const modal = page.getByRole('dialog')
      await expect(modal).toBeVisible()
      const box = await modal.boundingBox()
      expect(box).not.toBeNull()
      expect(box!.height).toBeLessThanOrEqual(520)
      await expectNoPageOverflow(page)
    })
  })
}

test.describe('mobile landscape', () => {
  test.use({ viewport: { width: 844, height: 390 } })
  test('catalog and detail pages do not create horizontal page scrolling', async ({ page }) => {
    await page.goto('/')
    await expectNoPageOverflow(page)
    await page.goto('/games/hades')
    await expect(page.getByRole('heading', { name: 'Hades' }).last()).toBeVisible()
    await expectNoPageOverflow(page)
  })
})
