const { test, expect } = require('@playwright/test');

test('creator tools surface music, H3 motion, and image studios', async ({ page }) => {
  await page.goto('/tools');

  await expect(page.getByRole('heading', { level: 1 })).toContainText('music, motion, and worlds');
  await expect(page.getByRole('heading', { name: 'Build the soundtrack.' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Give every frame a pulse.' })).toBeVisible();

  await expect(page.getByRole('link', { name: /Song Composer/ })).toHaveAttribute('href', 'https://manifoldgen.com/tools/music-generator');
  await expect(page.getByRole('link', { name: /Character Animator/ })).toHaveAttribute('href', 'https://manifoldgen.com/tools/character-animator');
  await expect(page.getByRole('link', { name: /H3 Video Studio/ })).toHaveAttribute('href', '/docs/h3_video');
  await expect(page.getByRole('link', { name: /Z-Image Playground/ })).toHaveAttribute('href', '/playground');
});
