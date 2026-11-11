const { test, expect } = require('@playwright/test');

// Two stable images so slugs are deterministic.
const IMAGES = [
  {
    id: '11111111-2222-3333-4444-555555555555',
    prompt: 'a magical fairy forest',
    width: 1024,
    height: 1024,
    file_path: 'a/orig.webp',
    thumb_path: 'a/thumb.webp',
    med_path: 'a/med.webp',
    file_size: 1234,
    model: 'z-image-turbo',
    seed: 42,
    steps: 8,
    created_at: '2026-01-01T00:00:00Z',
  },
  {
    id: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
    prompt: 'cyberpunk neon city',
    width: 1024,
    height: 1024,
    file_path: 'b/orig.webp',
    thumb_path: 'b/thumb.webp',
    med_path: 'b/med.webp',
    file_size: 5678,
    model: 'z-image-turbo',
    seed: 7,
    steps: 8,
    created_at: '2026-01-02T00:00:00Z',
  },
];

const SLUG_0 = 'a-magical-fairy-forest-11111111';
const SLUG_1 = 'cyberpunk-neon-city-aaaaaaaa';

// 1x1 transparent webp-ish gif so <img> requests resolve without noise.
const PIXEL = Buffer.from(
  'R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7',
  'base64'
);

async function mockGallery(page) {
  await page.route('**/api/images/count', route =>
    route.fulfill({ status: 200, json: { count: IMAGES.length } })
  );
  await page.route('**/api/images?**', route =>
    route.fulfill({ status: 200, json: { images: IMAGES, total: IMAGES.length } })
  );
  await page.route('**/api/prompt/**', route => {
    const url = new URL(route.request().url());
    const slug = decodeURIComponent(url.pathname.split('/api/prompt/')[1] || '');
    const short = slug.slice(slug.lastIndexOf('-') + 1);
    const img = IMAGES.find(i => i.id.split('-')[0] === short);
    if (!img) return route.fulfill({ status: 404, json: { error: 'not found' } });
    return route.fulfill({ status: 200, json: { image: img, related: [] } });
  });
  await page.route('**/images/**', route =>
    route.fulfill({ status: 200, contentType: 'image/gif', body: PIXEL })
  );
}

const dialog = page => page.getByRole('dialog', { name: 'Image detail' });
const firstTile = page =>
  page.locator('section[aria-label="Gallery results"] a').first();

test.describe('gallery modal URL + history', () => {
  test('clicking an image pushes /gallery/<slug> and shows the modal', async ({ page }) => {
    await mockGallery(page);
    await page.goto('/gallery', { waitUntil: 'networkidle' });

    await expect(dialog(page)).toBeHidden();
    await firstTile(page).click();

    await expect(page).toHaveURL(new RegExp(`/gallery/${SLUG_0}$`));
    await expect(dialog(page)).toBeVisible();
    await expect(dialog(page)).toContainText('a magical fairy forest');
  });

  test('browser Back closes the modal and restores /gallery', async ({ page }) => {
    await mockGallery(page);
    await page.goto('/gallery', { waitUntil: 'networkidle' });

    await firstTile(page).click();
    await expect(page).toHaveURL(new RegExp(`/gallery/${SLUG_0}$`));
    await expect(dialog(page)).toBeVisible();

    await page.goBack();
    await expect(page).toHaveURL(/\/gallery$/);
    await expect(dialog(page)).toBeHidden();

    // Forward re-opens the modal.
    await page.goForward();
    await expect(page).toHaveURL(new RegExp(`/gallery/${SLUG_0}$`));
    await expect(dialog(page)).toBeVisible();
  });

  test('close button returns to /gallery without leaving the page', async ({ page }) => {
    await mockGallery(page);
    await page.goto('/gallery', { waitUntil: 'networkidle' });

    await firstTile(page).click();
    await expect(dialog(page)).toBeVisible();

    await page.getByRole('button', { name: 'Close' }).click();
    await expect(page).toHaveURL(/\/gallery$/);
    await expect(dialog(page)).toBeHidden();
  });

  test('Escape key closes the modal and updates the URL', async ({ page }) => {
    await mockGallery(page);
    await page.goto('/gallery', { waitUntil: 'networkidle' });

    await firstTile(page).click();
    await expect(dialog(page)).toBeVisible();

    await page.keyboard.press('Escape');
    await expect(page).toHaveURL(/\/gallery$/);
    await expect(dialog(page)).toBeHidden();
  });

  test('deep link to /gallery/<slug> opens the modal directly', async ({ page }) => {
    await mockGallery(page);
    await page.goto(`/gallery/${SLUG_1}`, { waitUntil: 'networkidle' });

    await expect(page).toHaveURL(new RegExp(`/gallery/${SLUG_1}$`));
    await expect(dialog(page)).toBeVisible();
    await expect(dialog(page)).toContainText('cyberpunk neon city');

    // Closing a deep-linked modal rewrites to the bare gallery URL.
    await page.getByRole('button', { name: 'Close' }).click();
    await expect(page).toHaveURL(/\/gallery$/);
    await expect(dialog(page)).toBeHidden();
  });
});
