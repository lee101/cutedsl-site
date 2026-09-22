const { test, expect } = require('@playwright/test');

const TEST_EMAIL = 'home-billing@cutedsl.local';
const TEST_PASSWORD = 'home-billing-123';
const LINKED_WALLET = 'HomeBillingWallet111111111111111111111111111111';

async function installHomepageBillingMocks(page) {
  const emailWallet = 'email:homebilling000000000000000000000000000000';
  let user = null;
  let password = TEST_PASSWORD;
  let emailAuthCompleted = false;
  let balance = {
    wallet_address: emailWallet,
    credits: 0,
    credits_usd: 0,
    cute_price_usd: 0.01,
    total_deposited: 0,
    has_payment_method: false,
    has_password: true,
  };

  await page.route('https://js.stripe.com/v3/', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/javascript',
      body: `
        window.Stripe = function () {
          return {
            initEmbeddedCheckout: async function () {
              return {
                mount: function (target) {
                  const root = typeof target === 'string' ? document.querySelector(target) : target;
                  const checkout = document.createElement('div');
                  checkout.setAttribute('data-testid', 'mock-home-stripe-checkout');
                  checkout.textContent = 'Mock Home Stripe Checkout';
                  const frame = document.createElement('iframe');
                  frame.src = 'https://checkout.stripe.com/home-mock-session';
                  frame.title = 'Mock Home Stripe Checkout Frame';
                  root.appendChild(checkout);
                  root.appendChild(frame);
                },
                destroy: function () {
                  document.querySelectorAll('[data-testid="mock-home-stripe-checkout"], iframe[title="Mock Home Stripe Checkout Frame"]').forEach(el => el.remove());
                }
              };
            }
          };
        };
      `,
    });
  });

  await page.route('**/api/pricing', async route => {
    await route.fulfill({
      status: 200,
      json: {
        cute_price_usd: 0.01,
        sol_price_usd: 100,
        pricing: [{ service: 'zimage', price_usd: 0.04, price_cute: 4, cute_price_usd: 0.01, unit: 'generation' }],
      },
    });
  });

  await page.route('**/api/auth/email-login', async route => {
    const req = route.request().postDataJSON();
    if (!req.email || !req.password || req.password.length < 8) {
      await route.fulfill({ status: 400, json: { error: 'valid email and password required' } });
      return;
    }
    if (user && req.password !== password) {
      await route.fulfill({ status: 401, json: { error: 'invalid email or password' } });
      return;
    }
    if (!user) {
      password = req.password;
      user = {
        id: 'home_billing_user',
        wallet_address: emailWallet,
        email: req.email,
        api_key: 'cutedsl_home_billing_key',
      };
      balance = { ...balance, wallet_address: emailWallet, has_password: true };
    }
    emailAuthCompleted = true;
    await route.fulfill({ status: 200, json: { user, api_key: user.api_key, cute_price_usd: 0.01, credits_usd: balance.credits_usd } });
  });

  await page.route('**/api/auth/email', async route => {
    const req = route.request().postDataJSON();
    user = {
      id: 'home_billing_user',
      wallet_address: req.wallet_address,
      email: req.email,
      api_key: 'cutedsl_home_billing_key',
    };
    balance = { ...balance, wallet_address: req.wallet_address, has_password: !!req.password };
    await route.fulfill({ status: 200, json: { success: true, email: req.email, has_password: !!req.password, user } });
  });

  await page.route('**/api/auth/wallet', async route => {
    const req = route.request().postDataJSON();
    user = {
      id: 'home_billing_user',
      wallet_address: req.wallet_address,
      email: user?.email || TEST_EMAIL,
      api_key: req.api_key || 'cutedsl_home_billing_key',
    };
    balance = { ...balance, wallet_address: req.wallet_address };
    await route.fulfill({ status: 200, json: { user, api_key: user.api_key, linked: !!req.api_key, cute_price_usd: 0.01, credits_usd: 0 } });
  });

  await page.route('**/api/balance?**', async route => {
    await route.fulfill({ status: 200, json: balance });
  });

  await page.route('**/api/billing-history?**', async route => {
    await route.fulfill({ status: 200, json: { events: [] } });
  });

  await page.route('**/api/stripe-checkout', async route => {
    const req = route.request().postDataJSON();
    if (!req.wallet_address || req.amount_usd <= 0) {
      await route.fulfill({ status: 400, json: { error: 'wallet_address and amount_usd required' } });
      return;
    }
    if (!emailAuthCompleted) {
      await route.fulfill({ status: 409, json: { error: 'email must be captured before stripe checkout' } });
      return;
    }
    await route.fulfill({
      status: 200,
      json: {
        success: true,
        session_id: 'cs_test_home_billing',
        client_secret: 'cs_test_home_billing_secret',
        publishable_key: 'pk_test_home_billing',
      },
    });
  });
}

test('homepage captures email before Stripe checkout and links a Solana wallet for SOL flows', async ({ page }) => {
  await installHomepageBillingMocks(page);

  await page.goto('/');
  await page.locator('#credits').scrollIntoViewIfNeeded();

  await page.getByTestId('home-email').fill(TEST_EMAIL);
  await page.getByTestId('home-password').fill(TEST_PASSWORD);
  await page.getByTestId('home-email-continue').click();
  await expect(page.getByText(`Card login ready for ${TEST_EMAIL}`)).toBeVisible();

  await page.getByTestId('stripe-checkout-btn').click();

  await expect(page.getByText('Secure card checkout')).toBeVisible();
  await expect(page.getByTestId('mock-home-stripe-checkout')).toBeVisible();

  await page.getByRole('button', { name: /Close Stripe checkout/i }).click();
  await page.getByRole('button', { name: /Buy \$CUTEDSL/i }).click();
  await expect(page.getByText('Connect a Solana wallet to buy with SOL')).toBeVisible();

  page.once('dialog', async dialog => {
    await dialog.accept(LINKED_WALLET);
  });
  await page.getByRole('button', { name: /Connect wallet/i }).click();
  await expect(page.getByPlaceholder('0.1')).toBeVisible();
  await expect(page.getByText(/Wallet connected to your email account|Wallet connected/)).toBeVisible();
});
