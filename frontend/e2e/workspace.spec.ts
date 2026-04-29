import { expect, test } from '@playwright/test'
import { Buffer } from 'node:buffer'

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

test.describe('E2E workspace smoke', () => {
  test('renders deterministic auth route surfaces', async ({ page }) => {
    await page.goto('/auth')
    await expect(page.getByRole('heading', { name: 'E2E sign-in route is ready.' })).toBeVisible()
    await expect(page.getByText('E2E Demo User')).toBeVisible()

    await page.goto('/sign-up')
    await expect(page.getByRole('heading', { name: 'E2E sign-up route is ready.' })).toBeVisible()
    await expect(page.getByText('E2E Demo User')).toBeVisible()

    await page.goto('/')
    await expect(page.getByText('Research Workspace')).toBeVisible()
    await expect(page.getByText('E2E Demo User')).toBeVisible()
  })

  test('uploads a document, answers with citations, and abstains when unsupported', async ({
    page
  }) => {
    await page.goto('/')
    await expect(page.getByText('Research Workspace')).toBeVisible()

    const filename = `e2e-paris-${Date.now()}.txt`
    await page.locator('input[type="file"]').setInputFiles({
      name: filename,
      mimeType: 'text/plain',
      buffer: Buffer.from(
        [
          'Paris is the capital of France.',
          'This small document exists for deterministic browser smoke tests.'
        ].join('\n')
      )
    })

    await expect(page.getByRole('button', { name: new RegExp(escapeRegExp(filename)) })).toBeVisible()
    await expect(
      page.getByRole('button', { name: new RegExp(`${escapeRegExp(filename)}.*Ready`) })
    ).toBeVisible({ timeout: 45_000 })

    const composer = page.getByPlaceholder('Ask a question grounded in your documents...')
    await composer.fill('What is the capital of France?')
    await page.getByRole('button', { name: 'Ask Lumen' }).click()

    await expect(
      page.getByText('Paris is the capital of France, based on the uploaded document.')
    ).toBeVisible({ timeout: 30_000 })
    await expect(page.getByText('Strong evidence')).toBeVisible()
    await expect(page.getByLabel('Source citations')).toContainText(filename)
    await expect(page.getByLabel('Source citations')).toContainText(
      'Paris is the capital of France.'
    )

    await composer.fill('What does the document say about Mars geology?')
    await page.getByRole('button', { name: 'Ask Lumen' }).click()

    await expect(
      page.getByText(/support an answer to that from the uploaded documents/)
    ).toBeVisible({ timeout: 30_000 })
  })

  test('deletes an uploaded document after inline confirmation', async ({ page }) => {
    await page.goto('/')
    await expect(page.getByText('Research Workspace')).toBeVisible()

    const filename = `e2e-delete-${Date.now()}.txt`
    await page.locator('input[type="file"]').setInputFiles({
      name: filename,
      mimeType: 'text/plain',
      buffer: Buffer.from('This document exists only to verify the delete confirmation flow.')
    })

    const documentButton = page.getByRole('button', { name: new RegExp(escapeRegExp(filename)) })
    await expect(documentButton).toBeVisible()
    await documentButton.click()
    await page.getByRole('button', { name: 'Delete document' }).click()
    await expect(page.getByText('Delete permanently?')).toBeVisible()

    await page.getByRole('button', { name: 'Delete', exact: true }).click()

    await expect(documentButton).toHaveCount(0)
  })
})
