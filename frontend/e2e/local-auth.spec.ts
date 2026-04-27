import { expect, test } from '@playwright/test'

test.skip(
  process.env.PLAYWRIGHT_AUTH_MODE !== 'local',
  'Local auth smoke runs only against the local-auth Compose stack'
)

test.describe('Local auth smoke', () => {
  test('loads workspace without Clerk and shows the local user', async ({ page }) => {
    await page.goto('/')

    await expect(page.getByText('Research Workspace')).toBeVisible()
    await expect(page.getByText('Local Dev User')).toBeVisible()
    await expect(page.getByText('Checking your Clerk session.')).toHaveCount(0)
  })

  test('auth routes redirect to the local workspace instead of rendering Clerk', async ({ page }) => {
    await page.goto('/auth')

    await expect(page.getByText('Research Workspace')).toBeVisible()
    await expect(page.getByText('Local Dev User')).toBeVisible()
    await expect(page.getByText('Loading Clerk...')).toHaveCount(0)

    await page.goto('/sign-up')

    await expect(page.getByText('Research Workspace')).toBeVisible()
    await expect(page.getByText('Local Dev User')).toBeVisible()
    await expect(page.getByText('Loading Clerk...')).toHaveCount(0)
  })
})
