const { test, expect } = require('@playwright/test');

const userAgent = 'Mozilla/5.0 (Linux; Android 14; Z2458 Build/UP1A.231005.007; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/151.0.7922.199 Mobile Safari/537.36;AppTheme/light;cici;AppName/Dola';
const referrer = 'https://cutedsl.cc/image/real-life-cart-titan-from-attack-on-titan-caught-on-camera-hdr-4k-e9d2a47b?need_sec_link=1&sec_link_scene=im&theme=light';
test.use({ userAgent, viewport: { width: 360, height: 622 }, screen: { width: 360, height: 800 }, timezoneId: 'Asia/Manila', locale: 'en-US', isMobile: true });

for (const mode of ['null', 'undefined', 'getter-denied', 'methods-denied', 'quota']) {
  test(`storage ${mode}: pages hydrate and real errors still report`, async ({ page }) => {
    const errors = [];
    const reports = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.addInitScript(mode => {
      window.__storageReads = 0;
      for (const name of ['localStorage', 'sessionStorage']) {
        Object.defineProperty(window, name, {
          configurable: true,
          get() {
            if (name === 'localStorage') window.__storageReads++;
            if (mode === 'getter-denied') throw new DOMException('Storage disabled', 'SecurityError');
            if (mode === 'null') return null;
            if (mode === 'undefined') return undefined;
            return {
              getItem() {
                if (mode === 'methods-denied') throw new DOMException('Read denied', 'SecurityError');
                return null;
              },
              setItem() { throw new DOMException('Write denied', 'QuotaExceededError'); },
              removeItem() { throw new DOMException('Removal denied', 'SecurityError'); },
            };
          },
        });
      }
    }, mode);
    await page.route('**/api/**', route => {
      const path = new URL(route.request().url()).pathname;
      if (path === '/api/frontend-error') {
        reports.push(JSON.parse(route.request().postData()));
        return route.fulfill({ status: 202, json: {} });
      }
      if (path === '/api/auth/email-login') return route.fulfill({ json: {
        user: { wallet_address: 'email:storage-test', email: 'storage@example.com' }, api_key: 'storage-test-key',
      } });
      return route.fulfill({ json: { pricing: [], images: [], total: 0, count: 0, credits: 0, credits_usd: 0, has_password: true } });
    });
    for (const path of ['/', '/account', '/playground', '/docs']) {
      await page.goto(path, { referer: referrer, waitUntil: 'networkidle' });
      await expect(page.locator('h1').first()).toBeVisible();
      await expect.poll(() => page.evaluate(() => window.__storageReads)).toBeGreaterThan(0);
      expect(errors).toEqual([]);
      expect(reports).toEqual([]);
    }
    // Exercise a write after login, not just mount-time reads.
    await page.goto('/', { referer: referrer, waitUntil: 'networkidle' });
    // CDN network idle may precede React hydration; wait for the mount read.
    await expect.poll(() => page.evaluate(() => window.__storageReads)).toBeGreaterThan(0);
    await page.getByRole('button', { name: 'Start creating' }).click();
    await page.getByTestId('conversion-email').fill('storage@example.com');
    await page.getByTestId('conversion-password').fill('storage-test-password');
    await page.getByTestId('conversion-continue').click();
    await expect(page.getByText('Signed in as storage@example.com')).toBeVisible();
    expect(errors).toEqual([]);
    expect(reports).toEqual([]);
    await page.evaluate(() => {
      console.log('storage regression ordinary log');
      console.warn('storage regression ordinary warning');
      console.error('storage regression ordinary console error');
    });
    await page.waitForTimeout(300);
    expect(reports).toEqual([]);
    await page.evaluate(() => setTimeout(() => { throw new Error('storage regression intentional error'); }, 0));
    await expect.poll(() => reports.length).toBe(1);
    expect(reports[0].message).toContain('storage regression intentional error');
    expect(reports[0].level).toBe('error');
    // Storage is unusable in this mode, so the session id must come from the
    // in-memory fallback instead of collapsing to an empty string.
    expect(reports[0].sessionId).toBeTruthy();
  });
}

test('per-session error cap holds when storage is unusable', async ({ page }) => {
  const reports = [];
  await page.addInitScript(() => {
    for (const name of ['localStorage', 'sessionStorage']) {
      Object.defineProperty(window, name, {
        configurable: true,
        get() {
          return {
            getItem() { throw new DOMException('Read denied', 'SecurityError'); },
            setItem() { throw new DOMException('Write denied', 'QuotaExceededError'); },
            removeItem() { throw new DOMException('Removal denied', 'SecurityError'); },
          };
        },
      });
    }
  });
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/frontend-error') {
      reports.push(JSON.parse(route.request().postData()));
      return route.fulfill({ status: 202, json: {} });
    }
    return route.fulfill({ json: { pricing: [], images: [], total: 0, count: 0, credits: 0, credits_usd: 0, has_password: true } });
  });
  await page.goto('/gallery', { waitUntil: 'networkidle' });
  await expect(page.locator('h1').first()).toBeVisible();
  await page.evaluate(() => {
    for (let i = 0; i < 30; i++) {
      const error = new Error(`storage cap regression ${i}`);
      setTimeout(() => { throw error; }, 0);
    }
  });
  await page.waitForTimeout(1500);
  expect(reports.length).toBe(20);
  expect(new Set(reports.map(report => report.sessionId)).size).toBe(1);
  expect(reports[0].sessionId).toBeTruthy();
});
