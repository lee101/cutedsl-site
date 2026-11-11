const { test, expect } = require('@playwright/test');

const API_KEY = 'cutedsl_test_upload_key';
const WALLET = 'DocsUploadWallet1111111111111111111111111111';
const PUBLIC_URL = 'https://appstatic.app.nz/cutedsl/uploads/testuser/stt/abc123-speech.wav';
const UPLOAD_URL = 'https://f76d25b8b86cfa5638f43016510d8f77.r2.cloudflarestorage.com/appstatic/cutedsl/uploads/testuser/stt/abc123-speech.wav?X-Amz-Signature=test';

async function installMocks(page) {
  const uploaded = { contentType: null, bytes: 0 };

  await page.addInitScript(([wallet, apiKey]) => {
    localStorage.setItem('cutedsl_wallet', wallet);
    localStorage.setItem('cutedsl_api_key', apiKey);
  }, [WALLET, API_KEY]);

  await page.route('**/api/uploads/presign*', async route => {
    const auth = route.request().headers()['authorization'];
    if (auth !== `Bearer ${API_KEY}`) {
      await route.fulfill({ status: 401, json: { error: 'invalid API key' } });
      return;
    }
    await route.fulfill({
      status: 200,
      json: {
        upload_url: UPLOAD_URL,
        public_url: PUBLIC_URL,
        object_key: 'cutedsl/uploads/testuser/stt/abc123-speech.wav',
        content_type: 'audio/wav',
        expires_in: 900,
      },
    });
  });

  await page.route('https://f76d25b8b86cfa5638f43016510d8f77.r2.cloudflarestorage.com/**', async route => {
    const req = route.request();
    if (req.method() !== 'PUT') {
      await route.fulfill({ status: 405, body: '' });
      return;
    }
    uploaded.contentType = req.headers()['content-type'] || null;
    uploaded.bytes = (req.postDataBuffer() || Buffer.alloc(0)).length;
    await route.fulfill({ status: 200, body: '' });
  });

  await page.route('**/appstatic.app.nz/**', route => route.fulfill({ status: 200, contentType: 'audio/wav', body: '' }));

  await page.route('**/api/service', async route => {
    const body = route.request().postDataJSON();
    await route.fulfill({
      status: 200,
      json: {
        result: { text: 'hello from cutedsl', audio_url: body.audio_url },
        credits_used: 12,
        credits_remain: 4988,
        usd_equivalent: 0.012,
      },
    });
  });

  return uploaded;
}

test.use({
  launchOptions: {
    args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream'],
    ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH
      ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH }
      : {}),
  },
  permissions: ['microphone'],
});

test.describe('STT docs upload', () => {
  test('uploads an audio file and transcribes the public URL', async ({ page }) => {
    const uploaded = await installMocks(page);
    await page.goto('/docs/stt');

    await expect(page.getByTestId('upload-field-audio')).toBeVisible();

    await page.getByTestId('upload-input-audio').setInputFiles({
      name: 'speech.wav',
      mimeType: 'audio/wav',
      buffer: Buffer.alloc(2048, 1),
    });

    const urlInput = page.locator('input[type="text"]').filter({ hasNot: page.locator('[hidden]') }).first();
    await expect(urlInput).toHaveValue(PUBLIC_URL, { timeout: 15_000 });
    expect(uploaded.contentType).toBe('audio/wav');
    expect(uploaded.bytes).toBe(2048);

    await expect(page.getByTestId('upload-preview-audio')).toBeVisible();

    await page.getByRole('button', { name: /^Run$/ }).click();
    await expect(page.getByText('hello from cutedsl')).toBeVisible({ timeout: 15_000 });
  });

  test('example chip fills the sample audio URL', async ({ page }) => {
    await installMocks(page);
    await page.goto('/docs/stt');

    await page.getByTestId('use-example').first().click();
    await expect(page.getByTestId('upload-preview-audio')).toHaveAttribute(
      'src',
      /appstatic\.app\.nz\/cutedsl\/samples\/stt-sample-en\.mp3/,
    );
  });
});

test.describe('STT docs mic recording', () => {
  test('records from the mic and uploads the clip', async ({ page }) => {
    const uploaded = await installMocks(page);
    await page.goto('/docs/stt');

    await page.getByTestId('record-audio').click();
    await expect(page.getByTestId('stop-recording')).toBeVisible();
    await page.waitForTimeout(1500);
    await page.getByTestId('stop-recording').click();

    await expect(page.getByTestId('upload-preview-audio')).toBeVisible({ timeout: 20_000 });
    expect(uploaded.bytes).toBeGreaterThan(0);
    expect(uploaded.contentType).toMatch(/audio\//);
  });
});
