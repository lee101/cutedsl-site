const { test, expect } = require('@playwright/test');

test('search page stays hydrated when gallery APIs return errors', async ({ page }) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error.message));

  await page.route('**/api/images/count', route =>
    route.fulfill({ status: 500, json: { error: 'count failed' } }));
  await page.route('**/api/images?**', route =>
    route.fulfill({ status: 500, json: { error: 'search failed' } }));

  await page.goto('/search', { waitUntil: 'networkidle' });

  await expect(page).toHaveTitle(/CuteDSL/);
  await expect(page.getByRole('heading', { name: 'AI Art Gallery' })).toBeVisible();
  await expect(page.locator('body')).not.toContainText('Application error: a client-side exception');
  expect(pageErrors).toEqual([]);
});
