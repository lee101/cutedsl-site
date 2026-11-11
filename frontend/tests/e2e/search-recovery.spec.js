const { test, expect } = require('@playwright/test');

test.use({ viewport: { width: 1365, height: 900 }, locale: 'en-US', timezoneId: 'UTC' });

for (const failure of ['http', 'missing-total', 'invalid-images', 'null', 'invalid-json', 'network']) {
  test(`search recovers from ${failure} without a client exception`, async ({ page }) => {
    const errors = [];
    const reports = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/api/frontend-error', route => {
      reports.push(route.request().postData());
      return route.fulfill({ status: 202, json: {} });
    });
    await page.route('**/api/images/count', route => route.fulfill({ status: 500, json: { error: 'count failed' } }));
    let recovered = false;
    await page.route('**/api/images?**', route => {
      if (recovered) return route.fulfill({ json: { images: null, total: 0 } });
      if (failure === 'network') return route.abort('failed');
      if (failure === 'invalid-json') return route.fulfill({ contentType: 'text/html', body: '<html>unavailable</html>' });
      const responses = {
        http: { status: 500, json: { error: 'search failed' } },
        'missing-total': { json: { images: [] } },
        'invalid-images': { json: { images: {}, total: 10 } },
        null: { contentType: 'application/json', body: 'null' },
      };
      return route.fulfill(responses[failure]);
    });
    await page.goto('/search?monitor_check=1788706542810');
    await expect(page.getByRole('alert').filter({ hasText: 'Images are temporarily unavailable' })).toContainText('temporarily unavailable');
    await expect(page.getByRole('heading', { name: 'AI Art Gallery' })).toBeVisible();
    recovered = true;
    await page.getByRole('button', { name: 'Try again' }).click();
    await expect(page.getByRole('alert').filter({ hasText: 'Images are temporarily unavailable' })).toHaveCount(0);
    await expect(page.getByText('No images yet.', { exact: false })).toBeVisible();
    expect(errors).toEqual([]);
    expect(reports).toEqual([]);
  });
}

test('semantic search failure can be retried with the same query', async ({ page }) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/api/images/count', route => route.fulfill({ json: { count: 0 } }));
  await page.route('**/api/images?**', route => route.fulfill({ json: { images: [], total: 0 } }));
  await page.route('**/api/search?**', route => route.fulfill({ json: { results: [] } }));
  await page.route('**/api/autocomplete?**', route => route.fulfill({ json: { suggestions: [] } }));
  let recovered = false;
  await page.route('**/api/images/semantic?**', route => {
    expect(new URL(route.request().url()).searchParams.get('q')).toBe('watercolor cat');
    return route.fulfill(recovered ? { json: { images: null } } : { status: 503, json: { error: 'unavailable' } });
  });
  await page.goto('/search');
  await expect(page.getByText('No images yet.', { exact: false })).toBeVisible();
  await page.getByPlaceholder('Search prompts...', { exact: false }).fill('watercolor cat');
  await page.getByRole('button', { name: 'Search', exact: true }).click();
  await expect(page.getByRole('alert').filter({ hasText: 'Images are temporarily unavailable' })).toBeVisible();
  recovered = true;
  await page.getByRole('button', { name: 'Try again' }).click();
  await expect(page.getByText('No images found for "watercolor cat"')).toBeVisible();
  expect(errors).toEqual([]);
});

test('failed pagination preserves images and stops automatic retries', async ({ page }) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/api/images/count', route => route.fulfill({ json: { count: 2 } }));
  await page.route('**/images/**', route => route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8"/>' }));
  let attempts = 0;
  let recovered = false;
  const image = { id: 'test-image', prompt: 'First image', width: 512, height: 512, file_path: 'test.svg' };
  await page.route('**/api/images?**', route => {
    if (new URL(route.request().url()).searchParams.get('page') === '1') {
      return route.fulfill({ json: { images: [image], total: 2 } });
    }
    attempts++;
    return route.fulfill(recovered
      ? { json: { images: [{ ...image, id: 'second-image', prompt: 'Second image' }], total: 2 } }
      : { status: 500, json: { error: 'search failed' } });
  });
  await page.goto('/search');
  await expect(page.getByRole('img', { name: 'First image', exact: true })).toBeVisible();
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  const alert = page.getByRole('alert').filter({ hasText: 'Images are temporarily unavailable' });
  await expect(alert).toBeVisible();
  const failedAttempts = attempts;
  await page.waitForTimeout(700);
  expect(attempts).toBe(failedAttempts);
  await expect(page.getByRole('img', { name: 'First image', exact: true })).toBeVisible();
  recovered = true;
  await page.getByRole('button', { name: 'Try again' }).click();
  await expect(page.getByRole('img', { name: 'Second image', exact: true })).toBeVisible();
  expect(errors).toEqual([]);
});
