const { test, expect } = require('@playwright/test');

test.use({ ignoreHTTPSErrors: true });
test.skip(process.env.CUTEDSL_LOCAL_E2E !== '1', 'Set CUTEDSL_LOCAL_E2E=1 to run the cutedsl.local HTTPS Stripe smoke tests.');

async function signInWithWallet(page) {
  await page.goto('https://cutedsl.local:3443/account', { waitUntil: 'domcontentloaded' });
  await expect(page.getByRole('heading', { name: 'Account' })).toBeVisible();

  page.once('dialog', async dialog => {
    await dialog.accept(`E2EStripeWallet${Date.now()}111111111111111111111111`);
  });
  await page.getByRole('button', { name: /Connect Solana wallet/i }).click();
  await expect(page.getByText('Checkout')).toBeVisible({ timeout: 15000 });
}

async function expectEmbeddedCheckout(page, label) {
  await expect(page.getByText('Secure Stripe checkout', { exact: true })).toBeVisible({ timeout: 30000 });
  await expect(page.getByText(`Plan: ${label}`, { exact: true })).toBeVisible();

  await page.waitForFunction(() => {
    return Array.from(document.querySelectorAll('iframe')).some((frame) => {
      const src = frame.getAttribute('src') || '';
      return src.includes('stripe.com') || src.includes('checkout');
    });
  }, null, { timeout: 45000 });

  const stripeFrames = page.frames().filter(f => /stripe|checkout/i.test(f.url()));
  expect(stripeFrames.length).toBeGreaterThan(0);
}

test('monthly embedded Stripe checkout opens on cutedsl.local HTTPS account page', async ({ page }) => {
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('console', msg => {
    if (msg.type() === 'error') errors.push(msg.text());
  });

  await signInWithWallet(page);
  await expect(page.getByRole('heading', { name: 'Monthly' })).toBeVisible();

  await page.getByRole('button', { name: /Choose/i }).first().click();
  await expectEmbeddedCheckout(page, 'monthly');

  const severe = errors.filter(e => !/favicon|Failed to load resource|ResizeObserver|Third-party cookie/i.test(e));
  expect(severe).toEqual([]);
});

test('annual embedded Stripe checkout opens on cutedsl.local HTTPS account page', async ({ page }) => {
  await signInWithWallet(page);
  await expect(page.getByRole('heading', { name: 'Annual' })).toBeVisible();

  await page.getByRole('button', { name: /Choose/i }).nth(1).click();
  await expectEmbeddedCheckout(page, 'annual');
});

test('credits embedded Stripe checkout opens on cutedsl.local HTTPS account page', async ({ page }) => {
  await signInWithWallet(page);
  await expect(page.getByRole('heading', { name: 'Credits' })).toBeVisible();

  await page.getByRole('button', { name: /Buy credits/i }).click();
  await expectEmbeddedCheckout(page, 'credits');
});
