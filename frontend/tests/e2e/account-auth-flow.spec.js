const { test, expect } = require('@playwright/test');

const TEST_EMAIL = 'account-flow@cutedsl.local';
const TEST_PASSWORD = 'cute-test-123';
const RESET_PASSWORD = 'cute-test-456';
const WALLET_FIRST_ADDRESS = 'WalletFirstAccount111111111111111111111111111';
const WALLET_FIRST_EMAIL = 'wallet-first-account@cutedsl.local';
const WALLET_FIRST_PASSWORD = 'wallet-first-123';

async function installAccountMocks(page) {
  let user = null;
  let password = TEST_PASSWORD;
  const resetToken = 'reset-token-account-flow';

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
                  checkout.setAttribute('data-testid', 'mock-stripe-checkout');
                  checkout.textContent = 'Mock Stripe Embedded Checkout';
                  checkout.style.cssText = 'padding:24px;border:1px solid #cbd5e1;border-radius:8px;font-weight:700;';
                  const frame = document.createElement('iframe');
                  frame.src = 'https://checkout.stripe.com/mock-session';
                  frame.title = 'Mock Stripe Checkout Frame';
                  frame.style.cssText = 'width:100%;height:120px;border:0;margin-top:12px;';
                  root.appendChild(checkout);
                  root.appendChild(frame);
                },
                destroy: function () {
                  document.querySelectorAll('[data-testid="mock-stripe-checkout"], iframe[title="Mock Stripe Checkout Frame"]').forEach(el => el.remove());
                }
              };
            }
          };
        };
      `,
    });
  });

  await page.route('**/api/auth/email-login', async route => {
    const req = route.request().postDataJSON();
    if (!req.email || !req.email.includes('@') || !req.password || req.password.length < 8) {
      await route.fulfill({ status: 400, json: { error: 'valid email and password required' } });
      return;
    }
    if (user && req.email === user.email && req.password !== password) {
      await route.fulfill({ status: 401, json: { error: 'invalid email or password' } });
      return;
    }
    if (!user) {
      user = {
        id: 'user_account_flow',
        wallet_address: 'email:accountflow000000000000000000000000000000',
        email: req.email,
        api_key: 'cutedsl_account_flow_test_key',
      };
      password = req.password;
    }
    await route.fulfill({
      status: 200,
      json: {
        user,
        api_key: user.api_key,
        created: req.password === TEST_PASSWORD,
        cute_price_usd: 0.01,
        credits_usd: 0,
      },
    });
  });

  await page.route('**/api/auth/wallet', async route => {
    const req = route.request().postDataJSON();
    if (!req.wallet_address || req.wallet_address.length < 20) {
      await route.fulfill({ status: 400, json: { error: 'wallet_address required' } });
      return;
    }
    user = {
      id: 'user_account_flow',
      wallet_address: req.wallet_address,
      email: req.email || user?.email || '',
      api_key: 'cutedsl_account_flow_test_key',
    };
    await route.fulfill({ status: 200, json: { user, api_key: user.api_key, linked: !!req.api_key } });
  });

  await page.route('**/api/auth/email', async route => {
    const req = route.request().postDataJSON();
    if (!req.wallet_address || !req.email || !req.email.includes('@')) {
      await route.fulfill({ status: 400, json: { error: 'wallet_address and email required' } });
      return;
    }
    if (req.password && req.password.length < 8) {
      await route.fulfill({ status: 400, json: { error: 'password must be at least 8 characters' } });
      return;
    }
    user = {
      id: 'user_account_flow',
      wallet_address: req.wallet_address,
      email: req.email,
      api_key: user?.api_key || 'cutedsl_account_flow_test_key',
    };
    password = req.password || password;
    await route.fulfill({ status: 200, json: { success: true, user, email: req.email, has_password: !!req.password } });
  });

  await page.route('**/api/auth/forgot-password', async route => {
    await route.fulfill({ status: 200, json: { success: true, reset_token: resetToken } });
  });

  await page.route('**/api/auth/reset-password', async route => {
    const req = route.request().postDataJSON();
    if (req.token !== resetToken || !req.password || req.password.length < 8) {
      await route.fulfill({ status: 400, json: { error: 'invalid reset request' } });
      return;
    }
    password = req.password;
    user = user || {
      id: 'user_account_flow',
      wallet_address: 'email:accountflow000000000000000000000000000000',
      email: TEST_EMAIL,
      api_key: 'cutedsl_account_flow_test_key',
    };
    await route.fulfill({ status: 200, json: { success: true, user, api_key: user.api_key } });
  });

  await page.route('**/api/balance?**', async route => {
    await route.fulfill({
      status: 200,
      json: {
        wallet_address: user?.wallet_address || 'email:accountflow000000000000000000000000000000',
        credits: 0,
        credits_usd: 0,
        cute_price_usd: 0.01,
        total_deposited: 0,
        has_payment_method: false,
        unlimited_api: false,
        subscription_status: '',
        subscription_plan: '',
      },
    });
  });

  await page.route('**/api/billing-history?**', async route => {
    await route.fulfill({ status: 200, json: { events: [] } });
  });

  await page.route('**/api/stripe-checkout', async route => {
    const req = route.request().postDataJSON();
    if (!req.wallet_address) {
      await route.fulfill({ status: 400, json: { error: 'wallet_address required' } });
      return;
    }
    if (!user?.email) {
      await route.fulfill({ status: 400, json: { error: 'email required before stripe checkout' } });
      return;
    }
    await route.fulfill({
      status: 200,
      json: {
        success: true,
        session_id: 'cs_test_account_flow',
        customer_id: 'cus_test_account_flow',
        client_secret: 'cs_test_account_flow_secret',
        publishable_key: 'pk_test_account_flow',
        ui_mode: 'embedded',
        type: req.type || 'credits',
        plan: req.plan || 'monthly',
      },
    });
  });
}

test('signup, logout, login, reset password, and embedded checkout work on /account', async ({ page }) => {
  await installAccountMocks(page);

  await page.goto('/account');
  await expect(page.getByRole('heading', { name: 'Account' })).toBeVisible();

  await page.getByTestId('account-email').fill(TEST_EMAIL);
  await page.getByTestId('account-password').fill(TEST_PASSWORD);
  await page.getByRole('button', { name: /Login or create account/i }).click();
  await expect(page.getByText('Signed in', { exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Checkout' })).toBeVisible();

  await page.getByRole('button', { name: /Sign out/i }).click();
  await expect(page.getByRole('button', { name: /Login or create account/i })).toBeVisible();

  await page.getByTestId('account-email').fill(TEST_EMAIL);
  await page.getByTestId('account-password').fill(TEST_PASSWORD);
  await page.getByRole('button', { name: /Login or create account/i }).click();
  await expect(page.getByText('Signed in', { exact: true })).toBeVisible();

  await page.getByRole('button', { name: /Sign out/i }).click();
  await page.getByRole('button', { name: /Forgot password/i }).click();
  await page.getByLabel('Email').fill(TEST_EMAIL);
  await page.getByRole('button', { name: /Send reset link/i }).click();
  await page.getByLabel('New password').fill(RESET_PASSWORD);
  await page.getByRole('button', { name: /Reset password/i }).click();
  await expect(page.getByText('Password reset. You are signed in.')).toBeVisible();

  await page.getByRole('button', { name: /Choose/i }).first().click();
  const checkout = page.getByTestId('embedded-checkout-container');
  await expect(checkout).toBeVisible();
  await expect(checkout.getByText('Secure Stripe checkout')).toBeVisible();
  await expect(checkout.getByText('Plan: monthly')).toBeVisible();
  await expect(page.getByTestId('mock-stripe-checkout')).toBeVisible();
  await expect(page.locator('iframe[title="Mock Stripe Checkout Frame"]')).toHaveCount(1);
});

test('wallet-first users can add email and then pay with Stripe on /account', async ({ page }) => {
  await installAccountMocks(page);

  await page.goto('/account');
  page.once('dialog', async dialog => {
    await dialog.accept(WALLET_FIRST_ADDRESS);
  });
  await page.getByRole('button', { name: /Connect Solana wallet/i }).click();
  await expect(page.getByText('Wallet connected.')).toBeVisible();
  await expect(page.getByTestId('account-add-email-card')).toBeVisible();

  await page.getByRole('button', { name: /^Choose/i }).first().click();
  await expect(page.getByText('Add an email to this wallet before starting Stripe checkout.')).toBeVisible();

  await page.getByTestId('account-link-email').fill(WALLET_FIRST_EMAIL);
  await page.getByTestId('account-link-password').fill(WALLET_FIRST_PASSWORD);
  await page.getByRole('button', { name: /Save email and enable Stripe/i }).click();
  await expect(page.getByText('Email saved. Card checkout is ready.')).toBeVisible();
  await expect(page.getByTestId('account-add-email-card')).toHaveCount(0);

  await page.getByRole('button', { name: /^Choose/i }).first().click();
  const checkout = page.getByTestId('embedded-checkout-container');
  await expect(checkout).toBeVisible();
  await expect(checkout.getByText('Plan: monthly')).toBeVisible();
  await expect(page.getByTestId('mock-stripe-checkout')).toBeVisible();
});

test('/account?test=true runs the built-in account self-test and opens checkout', async ({ page }) => {
  await installAccountMocks(page);

  await page.goto('/account?test=true');
  await expect(page.getByTestId('account-self-test')).toBeVisible();
  await expect(page.getByText('Account E2E')).toBeVisible();
  await expect(page.getByTestId('account-test-signup-status')).toHaveText('passed');
  await expect(page.getByTestId('account-test-logout-status')).toHaveText('passed');
  await expect(page.getByTestId('account-test-login-status')).toHaveText('passed');
  await expect(page.getByTestId('account-test-reset-password-status')).toHaveText('passed');
  await expect(page.getByTestId('account-test-embedded-checkout-status')).toHaveText('passed');
  await expect(page.getByTestId('mock-stripe-checkout')).toBeVisible();
});
