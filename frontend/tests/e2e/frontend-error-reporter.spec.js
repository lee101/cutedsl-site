const { test, expect } = require('@playwright/test');

test('frontend error reporter filters scanner noise but keeps real errors', async ({ page }) => {
  const reportedErrors = [];
  const browserNoiseMessages = [
    'Object Not Found Matching Id:7, MethodName:update, ParamCount:4',
    'Object Not Found Matching Id:9, MethodName:simulateEvent, ParamCount:1',
  ];

  await page.route('**/api/images/count', async route => {
    await route.fulfill({ status: 200, json: { count: 100000 } });
  });
  await page.route('**/api/images?**', async route => {
    await route.fulfill({ status: 200, json: { images: [], total: 0 } });
  });
  await page.route('**/api/frontend-error', async route => {
    reportedErrors.push({
      body: route.request().postData() || '',
      origin: route.request().headers().origin || '',
    });
    await route.fulfill({
      status: 202,
      json: { status: 'logged', request_id: `test-${reportedErrors.length}` },
    });
  });

  await page.goto('/gallery', { waitUntil: 'networkidle' });
  // Network idle can precede React effects when scripts come from the CDN.
  await expect(page.getByText('No images yet.', { exact: true })).toBeVisible();

  await page.evaluate(() => {
    console.error('non-error console log should not be reported');
  });
  for (const browserNoiseMessage of browserNoiseMessages) {
    await page.evaluate(message => {
      setTimeout(() => {
        Promise.reject(message);
        Promise.reject(new Error(message));
        window.dispatchEvent(new ErrorEvent('error', {
          message,
          filename: '',
          lineno: 0,
          colno: 0,
          error: new Error(message),
        }));
      }, 0);
    }, browserNoiseMessage);
  }
  await page.waitForTimeout(500);
  expect(reportedErrors).toHaveLength(0);

  await page.evaluate(() => {
    setTimeout(() => {
      Promise.reject(new Error('cutedsl reporter regression check'));
    }, 0);
  });

  await expect.poll(() => reportedErrors.length).toBe(1);
  const report = JSON.parse(reportedErrors[0].body);
  expect(reportedErrors[0].origin).toBe(new URL(page.url()).origin);
  expect(report.message).toBe('cutedsl reporter regression check');
  expect(report.source).toBe('unhandledrejection');
  expect(report.level).toBe('error');
  expect(report.userAgent).toBeTruthy();
  expect(report.occurredAt).toMatch(/^\d{4}-\d{2}-\d{2}T/);
  expect(report.fingerprint).toContain('cutedsl reporter regression check');
  expect(report.viewport).toEqual(expect.objectContaining({ width: expect.any(Number), height: expect.any(Number) }));
  expect(report.screen).toEqual(expect.objectContaining({ width: expect.any(Number), height: expect.any(Number) }));
});

test('frontend error reporter survives restricted storage and beacon APIs', async ({ page }) => {
  const reportedErrors = [];

  await page.addInitScript(() => {
    Object.defineProperty(window, 'sessionStorage', {
      configurable: true,
      get() {
        throw new DOMException('Storage is disabled', 'SecurityError');
      },
    });
    Object.defineProperty(navigator, 'sendBeacon', {
      configurable: true,
      value: undefined,
    });
  });
  await page.route('**/api/images/count', route =>
    route.fulfill({ status: 200, json: { count: 100000 } }));
  await page.route('**/api/images?**', route =>
    route.fulfill({ status: 200, json: { images: [], total: 0 } }));
  await page.route('**/api/frontend-error', async route => {
    reportedErrors.push(JSON.parse(route.request().postData() || '{}'));
    await route.fulfill({
      status: 202,
      json: { status: 'logged', request_id: 'restricted-browser-test' },
    });
  });

  await page.goto('/gallery', { waitUntil: 'networkidle' });
  // Network idle can precede React effects when scripts come from the CDN.
  await expect(page.getByText('No images yet.', { exact: true })).toBeVisible();
  await page.evaluate(() => {
    console.error('restricted-browser console log');
    setTimeout(() => Promise.reject(new Error('restricted-browser real error')), 0);
  });

  await expect.poll(() => reportedErrors.length).toBe(1);
  expect(reportedErrors[0]).toEqual(expect.objectContaining({
    level: 'error',
    message: 'restricted-browser real error',
    source: 'unhandledrejection',
  }));
  expect(reportedErrors[0].sessionId).toBeTruthy();

  // Promise rejections are allowed to have no reason. JSON.stringify(undefined)
  // also returns undefined, so keep this case from crashing the reporter itself.
  await page.evaluate(() => {
    setTimeout(() => Promise.reject(), 0);
  });
  await expect.poll(() => reportedErrors.length).toBe(2);
  expect(reportedErrors[1]).toEqual(expect.objectContaining({
    level: 'error',
    message: 'Unhandled promise rejection',
    source: 'unhandledrejection',
    // sessionStorage is denied, so identity comes from the in-memory fallback
    // and must stay stable for the life of the page.
    sessionId: reportedErrors[0].sessionId,
  }));
});

test('frontend error reporter drops masked cross-origin script errors', async ({ page }) => {
  const reportedErrors = [];

  await page.route('**/api/images/count', route => route.fulfill({ status: 200, json: { count: 0 } }));
  await page.route('**/api/images?**', route => route.fulfill({ status: 200, json: { images: [], total: 0 } }));
  await page.route('**/api/frontend-error', async route => {
    reportedErrors.push(JSON.parse(route.request().postData() || '{}'));
    await route.fulfill({ status: 202, json: {} });
  });

  await page.goto('/gallery', { waitUntil: 'networkidle' });
  await expect(page.locator('h1').first()).toBeVisible();
  await page.evaluate(() => {
    // Exactly what the browser reports for a cross-origin script it refused to
    // attribute: no filename, position, or error object.
    window.dispatchEvent(new ErrorEvent('error', {
      message: 'Script error.',
      filename: '',
      lineno: 0,
      colno: 0,
      error: null,
    }));
  });
  await page.waitForTimeout(500);
  expect(reportedErrors).toEqual([]);

  await page.evaluate(() => {
    // Same message but attributed: an error we can actually act on, e.g. a CDN
    // chunk that failed after crossorigin was dropped.
    setTimeout(() => {
      window.dispatchEvent(new ErrorEvent('error', {
        message: 'Script error.',
        filename: 'https://appstatic.app.nz/cutedsl/static/chunk.js',
        lineno: 1,
        colno: 33,
        error: new Error('Script error.'),
      }));
    }, 0);
  });
  await expect.poll(() => reportedErrors.length).toBe(1);
  expect(reportedErrors[0]).toEqual(expect.objectContaining({
    message: 'Script error.',
    source: 'https://appstatic.app.nz/cutedsl/static/chunk.js',
    lineno: 1,
    colno: 33,
  }));
});

test('CDN script exceptions retain details when beacon throws', async ({ page }) => {
  const reports = [];
  await page.addInitScript(() => {
    Object.defineProperty(navigator, 'sendBeacon', {
      configurable: true,
      value() { throw new DOMException('Beacon disabled', 'SecurityError'); },
    });
  });
  await page.route('**/api/images/count', route => route.fulfill({ json: { count: 0 } }));
  await page.route('**/api/images?**', route => route.fulfill({ json: { images: [], total: 0 } }));
  await page.route('**/api/frontend-error', route => {
    reports.push(JSON.parse(route.request().postData()));
    return route.fulfill({ status: 202, json: {} });
  });
  await page.route('https://appstatic.app.nz/cutedsl/reporter-regression.js', route => route.fulfill({
    contentType: 'text/javascript',
    headers: { 'Access-Control-Allow-Origin': '*' },
    body: 'setTimeout(() => { throw new Error("CDN reporter regression"); }, 0);',
  }));
  await page.goto('/search', { waitUntil: 'networkidle' });
  await page.evaluate(() => {
    console.log('ordinary log');
    console.warn('ordinary warning');
    console.error('ordinary console error');
    const script = document.createElement('script');
    // Use the actual Next script policy; a missing policy recreates Script error.
    const nextScript = document.querySelector('script[src*="/_next/"]');
    if (nextScript.hasAttribute('crossorigin')) script.crossOrigin = nextScript.crossOrigin;
    script.src = 'https://appstatic.app.nz/cutedsl/reporter-regression.js';
    document.body.appendChild(script);
  });
  await expect.poll(() => reports.length).toBe(1);
  expect(reports[0].message).toContain('CDN reporter regression');
  expect(reports[0].source).toBe('https://appstatic.app.nz/cutedsl/reporter-regression.js');
  expect(reports[0].stack).toContain('CDN reporter regression');
  expect(reports[0].lineno).toBeGreaterThan(0);
});
