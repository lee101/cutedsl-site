'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import Image from 'next/image';
import Link from 'next/link';
import {
  ArrowRight,
  Check,
  Copy,
  CreditCard,
  Key,
  LogOut,
  Mail,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Wallet,
  X,
  Zap,
} from 'lucide-react';

const API_BASE = '/api';
const IMG_BASE = 'https://appstatic.app.nz/cutedsl/images';

interface StripeEmbeddedCheckout {
  mount: (target: string | HTMLElement) => void;
  destroy: () => void;
}

interface StripeBrowserClient {
  initEmbeddedCheckout: (options: {
    clientSecret: string;
    onComplete?: () => void;
  }) => Promise<StripeEmbeddedCheckout>;
}

interface SolanaProvider {
  isPhantom?: boolean;
  connect: () => Promise<{ publicKey: { toString: () => string } }>;
  disconnect?: () => Promise<void> | void;
}

declare global {
  interface Window {
    Stripe?: (publishableKey: string) => StripeBrowserClient;
    solana?: SolanaProvider;
  }
}

let stripeJsPromise: Promise<void> | null = null;

function loadStripeJS() {
  if (typeof window === 'undefined') return Promise.reject(new Error('Stripe.js requires a browser'));
  if (window.Stripe) return Promise.resolve();
  if (stripeJsPromise) return stripeJsPromise;

  stripeJsPromise = new Promise((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>('script[src="https://js.stripe.com/v3/"]');
    if (existing) {
      existing.addEventListener('load', () => resolve(), { once: true });
      existing.addEventListener('error', () => reject(new Error('Failed to load Stripe.js')), { once: true });
      return;
    }

    const script = document.createElement('script');
    script.src = 'https://js.stripe.com/v3/';
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error('Failed to load Stripe.js'));
    document.head.appendChild(script);
  });

  return stripeJsPromise;
}

interface UserPayload {
  id: string;
  wallet_address: string;
  email?: string;
  api_key: string;
  unlimited_api?: boolean;
  subscription_status?: string;
  subscription_plan?: string;
}

interface BalancePayload {
  wallet_address: string;
  credits: number;
  credits_usd: number;
  cute_price_usd: number;
  total_deposited: number;
  has_payment_method?: boolean;
  autotopup_enabled?: boolean;
  autotopup_threshold_usd?: number;
  autotopup_amount_usd?: number;
  unlimited_api?: boolean;
  subscription_status?: string;
  subscription_plan?: string;
}

interface BillingEvent {
  id: string;
  event_type: string;
  amount: number;
  description: string;
  created_at: string;
}

interface AuthResponse {
  user: UserPayload;
  api_key: string;
}

interface BillingHistoryResponse {
  events?: BillingEvent[];
}

interface PasswordResetRequestResponse {
  reset_token?: string;
}

interface CheckoutResponse {
  client_secret?: string;
  publishable_key?: string;
  session_id?: string;
}

interface AutotopupResponse {
  enabled?: boolean;
}

interface UpdateEmailResponse {
  user: UserPayload;
}

type CheckoutKind = 'credits' | 'monthly' | 'annual';
type AccountTestStatus = 'running' | 'passed' | 'failed' | 'skipped';

interface AccountTestResult {
  step: string;
  status: AccountTestStatus;
  detail?: string;
}

const inputClassName = 'mt-2 w-full rounded-lg border border-pink-100 bg-white px-3 py-3 text-base outline-none focus:border-pink-400 focus:ring-2 focus:ring-pink-100';
const primaryButtonClassName = 'inline-flex w-full items-center justify-center gap-2 rounded-lg bg-pink-600 px-4 py-3 text-sm font-bold text-white hover:bg-pink-500 disabled:bg-slate-400 disabled:opacity-70';
const secondaryButtonClassName = 'w-full rounded-lg px-4 py-2 text-sm font-bold text-slate-600 hover:bg-slate-100';
const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function formatCute(n: number) {
  if (!Number.isFinite(n)) return '0';
  if (n >= 1000000) return `${(n / 1000000).toFixed(1)}M`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}K`;
  return n.toFixed(0);
}

function statusTone(message: string) {
  const lower = message.toLowerCase();
  if (lower.includes('failed') || lower.includes('error') || lower.includes('required') || lower.includes('cancel')) {
    return 'border-red-200 bg-red-50 text-red-700';
  }
  return 'border-emerald-200 bg-emerald-50 text-emerald-700';
}

function isValidEmail(value: string) {
  return emailPattern.test(value.trim());
}

function errorMessage(err: unknown, fallback: string) {
  return err instanceof Error ? err.message : fallback;
}

async function parseResponse<T>(res: Response, fallback: string): Promise<T> {
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const message = typeof data === 'object' && data && 'error' in data && typeof data.error === 'string'
      ? data.error
      : fallback;
    throw new Error(message);
  }
  return data as T;
}

async function postJSON<T>(path: string, payload: Record<string, unknown>, fallback: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return parseResponse<T>(res, fallback);
}

export default function AccountPage() {
  const [walletAddress, setWalletAddress] = useState<string | null>(null);
  const [email, setEmail] = useState<string | null>(null);
  const [emailInput, setEmailInput] = useState('');
  const [apiKey, setApiKey] = useState<string | null>(null);
  const [balance, setBalance] = useState<BalancePayload | null>(null);
  const [events, setEvents] = useState<BillingEvent[]>([]);
  const [loadingAuth, setLoadingAuth] = useState(false);
  const [loadingWallet, setLoadingWallet] = useState(false);
  const [password, setPassword] = useState('');
  const [forgotMode, setForgotMode] = useState(false);
  const [resetToken, setResetToken] = useState('');
  const [resetPassword, setResetPassword] = useState('');
  const [checkoutKind, setCheckoutKind] = useState<CheckoutKind>('monthly');
  const [checkoutLoading, setCheckoutLoading] = useState(false);
  const [creditsAmount, setCreditsAmount] = useState('25');
  const [stripePublishableKey, setStripePublishableKey] = useState('');
  const [embeddedSecret, setEmbeddedSecret] = useState('');
  const [status, setStatus] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [autotopupEnabled, setAutotopupEnabled] = useState(false);
  const [autotopupThreshold, setAutotopupThreshold] = useState('5');
  const [autotopupAmount, setAutotopupAmount] = useState('25');
  const [autotopupSaving, setAutotopupSaving] = useState(false);
  const [testMode, setTestMode] = useState(false);
  const [accountTestResults, setAccountTestResults] = useState<AccountTestResult[]>([]);
  const checkoutElementRef = useRef<HTMLDivElement | null>(null);
  const embeddedCheckoutRef = useRef<StripeEmbeddedCheckout | null>(null);
  const selfTestStartedRef = useRef(false);

  const signedIn = !!walletAddress && !!apiKey;
  const canSubmitEmailLogin = isValidEmail(emailInput) && password.length >= 8;

  const storeAuth = useCallback((user: UserPayload, key: string) => {
    setWalletAddress(user.wallet_address);
    setApiKey(key);
    setEmail(user.email || null);
    localStorage.setItem('cutedsl_wallet', user.wallet_address);
    localStorage.setItem('cutedsl_api_key', key);
    if (user.email) {
      setEmailInput(user.email);
      localStorage.setItem('cutedsl_email', user.email);
    } else {
      localStorage.removeItem('cutedsl_email');
    }
  }, []);

  const refreshAccount = useCallback(async (wallet: string) => {
    const [balanceRes, historyRes] = await Promise.all([
      fetch(`${API_BASE}/balance?wallet=${encodeURIComponent(wallet)}`),
      fetch(`${API_BASE}/billing-history?wallet=${encodeURIComponent(wallet)}`),
    ]);
    const balanceData = await parseResponse<BalancePayload>(balanceRes, 'Failed to load account balance');
    const historyData = await parseResponse<BillingHistoryResponse>(historyRes, 'Failed to load billing history');
    setBalance(balanceData);
    setEvents(historyData.events || []);
    setAutotopupEnabled(!!balanceData.autotopup_enabled);
    if (balanceData.autotopup_threshold_usd) setAutotopupThreshold(String(balanceData.autotopup_threshold_usd));
    if (balanceData.autotopup_amount_usd) setAutotopupAmount(String(balanceData.autotopup_amount_usd));
  }, []);

  useEffect(() => {
    const savedWallet = localStorage.getItem('cutedsl_wallet');
    const savedKey = localStorage.getItem('cutedsl_api_key');
    const savedEmail = localStorage.getItem('cutedsl_email');
    const params = new URLSearchParams(window.location.search);
    if (savedWallet) setWalletAddress(savedWallet);
    if (savedKey) setApiKey(savedKey);
    if (savedEmail) {
      setEmail(savedEmail);
      setEmailInput(savedEmail);
    }

    const payment = params.get('payment');
    const token = params.get('reset_token');
    if (payment === 'success') setStatus('Stripe checkout completed. Your account will update after confirmation.');
    if (token) {
      setResetToken(token);
      setForgotMode(false);
    }
    if (params.get('test') === 'true') {
      setTestMode(true);
    }
  }, []);

  useEffect(() => {
    if (!walletAddress) return;
    refreshAccount(walletAddress).catch(() => {});
    const id = window.setInterval(() => refreshAccount(walletAddress).catch(() => {}), 30000);
    return () => window.clearInterval(id);
  }, [walletAddress, refreshAccount]);

  useEffect(() => {
    if (!embeddedSecret || !stripePublishableKey || !checkoutElementRef.current) return;

    let cancelled = false;
    const mount = async () => {
      try {
        embeddedCheckoutRef.current?.destroy();
        embeddedCheckoutRef.current = null;
        await loadStripeJS();
        if (cancelled) return;
        const stripe = window.Stripe?.(stripePublishableKey);
        if (!stripe) throw new Error('Stripe.js did not initialize');
        const checkout = await stripe.initEmbeddedCheckout({
          clientSecret: embeddedSecret,
          onComplete: () => {
            setStatus('Checkout complete. Refreshing account state.');
            setEmbeddedSecret('');
            if (walletAddress) refreshAccount(walletAddress).catch(() => {});
          },
        });
        if (cancelled) {
          checkout.destroy();
          return;
        }
        embeddedCheckoutRef.current = checkout;
        checkout.mount(checkoutElementRef.current!);
      } catch (err: unknown) {
        setStatus(errorMessage(err, 'Failed to load embedded checkout'));
        setEmbeddedSecret('');
      }
    };
    mount();

    return () => {
      cancelled = true;
      embeddedCheckoutRef.current?.destroy();
      embeddedCheckoutRef.current = null;
    };
  }, [embeddedSecret, stripePublishableKey, walletAddress, refreshAccount]);

  const emailLogin = async () => {
    if (!canSubmitEmailLogin) return;
    setLoadingAuth(true);
    setStatus(null);
    try {
      const data = await postJSON<AuthResponse>('/auth/email-login', { email: emailInput.trim(), password }, 'Login failed');
      storeAuth(data.user, data.api_key);
      setStatus('Signed in. Your API key and billing account are ready.');
    } catch (err: unknown) {
      setStatus(errorMessage(err, 'Login failed'));
    } finally {
      setLoadingAuth(false);
    }
  };

  const requestPasswordReset = async () => {
    if (!isValidEmail(emailInput)) return;
    setLoadingAuth(true);
    setStatus(null);
    try {
      const data = await postJSON<PasswordResetRequestResponse>('/auth/forgot-password', { email: emailInput.trim() }, 'Failed to request reset');
      if (data.reset_token) setResetToken(data.reset_token);
      setStatus('If that email exists, a reset link has been sent.');
    } catch (err: unknown) {
      setStatus(errorMessage(err, 'Failed to request reset'));
    } finally {
      setLoadingAuth(false);
    }
  };

  const submitPasswordReset = async () => {
    if (!resetToken || resetPassword.length < 8) return;
    setLoadingAuth(true);
    setStatus(null);
    try {
      const data = await postJSON<AuthResponse>('/auth/reset-password', { token: resetToken, password: resetPassword }, 'Failed to reset password');
      storeAuth(data.user, data.api_key);
      setPassword(resetPassword);
      setResetPassword('');
      setResetToken('');
      window.history.replaceState({}, '', '/account');
      setStatus('Password reset. You are signed in.');
    } catch (err: unknown) {
      setStatus(errorMessage(err, 'Failed to reset password'));
    } finally {
      setLoadingAuth(false);
    }
  };

  const connectWallet = async () => {
    setLoadingWallet(true);
    setStatus(null);
    try {
      const solana = window.solana;
      let addr = '';
      if (solana?.isPhantom) {
        const resp = await solana.connect();
        addr = resp.publicKey.toString();
      } else {
        addr = window.prompt('Enter your Solana wallet address:') || '';
      }
      if (addr.length < 20) throw new Error('Wallet address required');
      const data = await postJSON<AuthResponse>('/auth/wallet', {
        wallet_address: addr,
        email: isValidEmail(emailInput) ? emailInput.trim() : undefined,
      }, 'Wallet login failed');
      storeAuth(data.user, data.api_key);
      setStatus('Wallet connected.');
    } catch (err: unknown) {
      setStatus(errorMessage(err, 'Wallet login failed'));
    } finally {
      setLoadingWallet(false);
    }
  };

  const saveEmailForStripe = async () => {
    if (!walletAddress || !apiKey || !isValidEmail(emailInput)) return;
    if (password && password.length < 8) return;
    setLoadingAuth(true);
    setStatus(null);
    try {
      const data = await postJSON<UpdateEmailResponse>('/auth/email', {
        wallet_address: walletAddress,
        email: emailInput.trim(),
        password: password || undefined,
      }, 'Failed to save email');
      storeAuth(data.user, apiKey);
      setStatus('Email saved. Card checkout is ready.');
    } catch (err: unknown) {
      setStatus(errorMessage(err, 'Failed to save email'));
    } finally {
      setLoadingAuth(false);
    }
  };

  const logout = useCallback(() => {
    embeddedCheckoutRef.current?.destroy();
    embeddedCheckoutRef.current = null;
    setWalletAddress(null);
    setEmail(null);
    setApiKey(null);
    setBalance(null);
    setEvents([]);
    setEmbeddedSecret('');
    localStorage.removeItem('cutedsl_wallet');
    localStorage.removeItem('cutedsl_api_key');
    localStorage.removeItem('cutedsl_email');
    try {
      if (window.solana?.isPhantom) window.solana.disconnect?.();
    } catch {}
  }, []);

  const setTestStep = (step: string, status: AccountTestStatus, detail?: string) => {
    setAccountTestResults((current) => {
      const next = current.filter((result) => result.step !== step);
      return [...next, { step, status, detail }];
    });
  };

  const runAccountSelfTest = useCallback(async () => {
    const testEmail = `account-e2e-${Date.now()}@cutedsl.local`;
    const password = 'cute-test-123';
    const newPassword = 'cute-test-456';

    try {
      setAccountTestResults([]);
      setStatus(null);
      setEmailInput(testEmail);
      setPassword(password);
      logout();

      setTestStep('signup', 'running');
      const signup = await postJSON<AuthResponse>('/auth/email-login', { email: testEmail, password }, 'Signup failed');
      storeAuth(signup.user, signup.api_key);
      await refreshAccount(signup.user.wallet_address);
      setTestStep('signup', 'passed', testEmail);

      setTestStep('account', 'running');
      if (!signup.user.wallet_address || !signup.api_key) throw new Error('missing account auth payload');
      setTestStep('account', 'passed', '/account loaded with API key');

      setTestStep('logout', 'running');
      logout();
      setTestStep('logout', 'passed');

      setTestStep('login', 'running');
      const login = await postJSON<AuthResponse>('/auth/email-login', { email: testEmail, password }, 'Login failed');
      storeAuth(login.user, login.api_key);
      await refreshAccount(login.user.wallet_address);
      setTestStep('login', 'passed');

      setTestStep('reset password', 'running');
      const forgot = await postJSON<PasswordResetRequestResponse>('/auth/forgot-password', { email: testEmail }, 'Failed to request reset');
      if (forgot.reset_token) {
        const reset = await postJSON<AuthResponse>('/auth/reset-password', { token: forgot.reset_token, password: newPassword }, 'Failed to reset password');
        storeAuth(reset.user, reset.api_key);
        await refreshAccount(reset.user.wallet_address);
        setTestStep('reset password', 'passed');
      } else {
        setTestStep('reset password', 'skipped', 'reset token hidden outside dev/debug mode');
      }

      setTestStep('embedded checkout', 'running');
      const checkout = await postJSON<CheckoutResponse>('/stripe-checkout', {
        wallet_address: localStorage.getItem('cutedsl_wallet') || login.user.wallet_address,
        type: 'subscription',
        plan: 'monthly',
        return_url: `${window.location.origin}/account?payment=success&session_id={CHECKOUT_SESSION_ID}`,
      }, 'Failed to start checkout');
      if (!checkout.client_secret || !checkout.publishable_key) {
        throw new Error('checkout response missing embedded client secret');
      }
      setCheckoutKind('monthly');
      setStripePublishableKey(checkout.publishable_key);
      setEmbeddedSecret(checkout.client_secret);
      setStatus('Account self-test opened an embedded Stripe checkout.');
      setTestStep('embedded checkout', 'passed', checkout.session_id || 'session created');
    } catch (err: unknown) {
      const message = errorMessage(err, 'Account self-test failed');
      setTestStep('failure', 'failed', message);
      setStatus(message);
    }
  }, [logout, refreshAccount, storeAuth]);

  useEffect(() => {
    if (!testMode || selfTestStartedRef.current) return;
    selfTestStartedRef.current = true;
    runAccountSelfTest();
  }, [testMode, runAccountSelfTest]);

  const startCheckout = async (kind: CheckoutKind) => {
    if (!walletAddress) return;
    if (!email) {
      setStatus('Add an email to this wallet before starting Stripe checkout.');
      return;
    }
    setCheckoutKind(kind);
    setCheckoutLoading(true);
    setStatus(null);
    setEmbeddedSecret('');

    try {
      const body: Record<string, unknown> = {
        wallet_address: walletAddress,
        return_url: `${window.location.origin}/account?payment=success&session_id={CHECKOUT_SESSION_ID}`,
      };
      if (kind === 'credits') {
        body.type = 'credits';
        body.amount_usd = parseFloat(creditsAmount || '0');
      } else {
        body.type = 'subscription';
        body.plan = kind;
      }

      const data = await postJSON<CheckoutResponse>('/stripe-checkout', body, 'Failed to start checkout');
      if (!data.client_secret || !data.publishable_key) throw new Error('Stripe checkout did not return an embedded client secret');
      setStripePublishableKey(data.publishable_key);
      setEmbeddedSecret(data.client_secret);
      setStatus('Complete the secure Stripe checkout below.');
    } catch (err: unknown) {
      setStatus(errorMessage(err, 'Checkout failed'));
    } finally {
      setCheckoutLoading(false);
    }
  };

  const saveAutotopup = async () => {
    if (!walletAddress) return;
    setAutotopupSaving(true);
    setStatus(null);
    try {
      const data = await postJSON<AutotopupResponse>('/autotopup-settings', {
        wallet_address: walletAddress,
        enabled: autotopupEnabled,
        threshold_usd: parseFloat(autotopupThreshold || '5'),
        amount_usd: parseFloat(autotopupAmount || '25'),
      }, 'Failed to save auto top-up');
      setAutotopupEnabled(!!data.enabled);
      setStatus(data.enabled ? 'Auto top-up enabled.' : 'Auto top-up disabled.');
      await refreshAccount(walletAddress);
    } catch (err: unknown) {
      setStatus(errorMessage(err, 'Failed to save auto top-up'));
    } finally {
      setAutotopupSaving(false);
    }
  };

  const copyApiKey = async () => {
    if (!apiKey) return;
    await navigator.clipboard.writeText(apiKey);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 2000);
  };

  const activePlan = balance?.subscription_plan || '';
  const activeSubscription = !!balance?.unlimited_api && (balance.subscription_status === 'active' || balance.subscription_status === 'trialing');

  return (
    <main className="min-h-screen bg-[linear-gradient(135deg,#fff7fb_0%,#f8fbff_52%,#f6fff9_100%)] text-slate-900">
      <header className="border-b border-pink-100 bg-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-5 py-4">
          <Link href="/" className="flex items-center gap-3">
            <Image src={`${IMG_BASE}/logo.webp`} alt="CuteDSL" width={40} height={40} className="rounded-lg" />
            <span className="font-fredoka text-2xl font-bold text-slate-900">CuteDSL</span>
          </Link>
          <div className="flex items-center gap-3">
            <Link href="/docs" className="hidden rounded-lg px-3 py-2 text-sm font-bold text-slate-600 hover:bg-slate-100 sm:inline-flex">
              Docs
            </Link>
            <Link href="/gallery" className="hidden rounded-lg px-3 py-2 text-sm font-bold text-slate-600 hover:bg-slate-100 sm:inline-flex">
              Gallery
            </Link>
            {signedIn && (
              <button onClick={logout} className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-bold text-slate-600 hover:border-red-200 hover:text-red-600">
                <LogOut size={16} />
                Sign out
              </button>
            )}
          </div>
        </div>
      </header>

      <section className="mx-auto grid max-w-7xl gap-6 px-4 py-6 sm:px-5 sm:py-8 lg:grid-cols-[0.9fr_1.3fr]">
        <div className="space-y-6">
          <div className="rounded-lg border border-pink-100 bg-white/95 p-5 shadow-sm shadow-pink-100/40 sm:p-6">
            <div className="mb-5 flex items-start justify-between gap-4">
              <div>
                <h1 className="font-fredoka text-4xl font-bold text-slate-950">Account</h1>
                <p className="mt-2 text-sm text-slate-600">Login, manage API access, subscribe, and keep credits topped up.</p>
              </div>
              <div className="rounded-lg bg-pink-50 p-3 text-emerald-700">
                <ShieldCheck size={24} />
              </div>
            </div>

            {!signedIn ? (
              <div className="space-y-4">
                {resetToken ? (
                  <div className="space-y-3">
                    <label className="block text-sm font-bold text-slate-700">
                      New password
                      <input
                        type="password"
                        value={resetPassword}
                        onChange={(e) => setResetPassword(e.target.value)}
                        onKeyDown={(e) => e.key === 'Enter' && submitPasswordReset()}
                        placeholder="At least 8 characters"
                        className={inputClassName}
                      />
                    </label>
                    <button
                      onClick={submitPasswordReset}
                      disabled={loadingAuth || resetPassword.length < 8}
                      className={primaryButtonClassName}
                    >
                      {loadingAuth ? <RefreshCw size={16} className="animate-spin" /> : <Key size={16} />}
                      Reset password
                    </button>
                  </div>
                ) : forgotMode ? (
                  <div className="space-y-3">
                    <label className="block text-sm font-bold text-slate-700">
                      Email
                      <input
                        type="email"
                        value={emailInput}
                        onChange={(e) => setEmailInput(e.target.value)}
                        onKeyDown={(e) => e.key === 'Enter' && requestPasswordReset()}
                        placeholder="you@example.com"
                        className={inputClassName}
                      />
                    </label>
                    <button
                      onClick={requestPasswordReset}
                      disabled={loadingAuth || !isValidEmail(emailInput)}
                      className={primaryButtonClassName}
                    >
                      {loadingAuth ? <RefreshCw size={16} className="animate-spin" /> : <Mail size={16} />}
                      Send reset link
                    </button>
                    <button onClick={() => setForgotMode(false)} className={secondaryButtonClassName}>
                      Back to login
                    </button>
                  </div>
                ) : (
                  <div className="space-y-3">
                    <label className="block text-sm font-bold text-slate-700">
                      Email
                      <input
                        type="email"
                        value={emailInput}
                        data-testid="account-email"
                        onChange={(e) => setEmailInput(e.target.value)}
                        placeholder="you@example.com"
                        className={inputClassName}
                      />
                    </label>
                    <label className="block text-sm font-bold text-slate-700">
                      Password
                      <input
                        type="password"
                        value={password}
                        data-testid="account-password"
                        onChange={(e) => setPassword(e.target.value)}
                        onKeyDown={(e) => e.key === 'Enter' && emailLogin()}
                        placeholder="At least 8 characters"
                        className={inputClassName}
                      />
                    </label>
                    <button
                      onClick={emailLogin}
                      disabled={loadingAuth || !canSubmitEmailLogin}
                      className={primaryButtonClassName}
                    >
                      {loadingAuth ? <RefreshCw size={16} className="animate-spin" /> : <Mail size={16} />}
                      Login or create account
                    </button>
                    <button onClick={() => setForgotMode(true)} className={secondaryButtonClassName}>
                      Forgot password?
                    </button>
                  </div>
                )}
                <button
                  onClick={connectWallet}
                  disabled={loadingWallet}
                  className="flex w-full items-center justify-center gap-2 rounded-lg border border-pink-200 bg-white px-4 py-3 text-sm font-bold text-slate-800 hover:border-pink-400 hover:bg-pink-50 disabled:opacity-50"
                >
                  {loadingWallet ? <RefreshCw size={16} className="animate-spin" /> : <Wallet size={16} />}
                  Connect Solana wallet
                </button>
              </div>
            ) : (
              <div className="space-y-4">
                <div className="rounded-lg border border-pink-100 bg-pink-50/50 p-4">
                  <div className="text-xs font-bold uppercase tracking-wide text-slate-500">Signed in</div>
                  <div className="mt-1 truncate text-sm font-bold text-slate-900">{email || walletAddress}</div>
                  <div className="mt-1 truncate font-mono text-xs text-slate-500">{walletAddress}</div>
                </div>

                {!email && (
                  <div className="rounded-lg border border-amber-200 bg-amber-50 p-4" data-testid="account-add-email-card">
                    <div className="mb-3 text-sm font-bold text-slate-800">Add email for card checkout</div>
                    <div className="space-y-3">
                      <label className="block text-xs font-bold text-slate-600">
                        Email
                        <input
                          type="email"
                          value={emailInput}
                          data-testid="account-link-email"
                          onChange={(e) => setEmailInput(e.target.value)}
                          placeholder="you@example.com"
                          className={inputClassName}
                        />
                      </label>
                      <label className="block text-xs font-bold text-slate-600">
                        Password for email login
                        <input
                          type="password"
                          value={password}
                          data-testid="account-link-password"
                          onChange={(e) => setPassword(e.target.value)}
                          onKeyDown={(e) => e.key === 'Enter' && saveEmailForStripe()}
                          placeholder="Optional, at least 8 characters"
                          className={inputClassName}
                        />
                      </label>
                      <button
                        type="button"
                        onClick={saveEmailForStripe}
                        disabled={loadingAuth || !isValidEmail(emailInput) || (!!password && password.length < 8)}
                        className={primaryButtonClassName}
                      >
                        {loadingAuth ? <RefreshCw size={16} className="animate-spin" /> : <Mail size={16} />}
                        Save email and enable Stripe
                      </button>
                    </div>
                  </div>
                )}

                <div className="grid grid-cols-2 gap-3">
                  <div className="rounded-lg border border-pink-100 bg-white p-4">
                    <div className="text-xs font-bold uppercase tracking-wide text-slate-500">Credits</div>
                    <div className="mt-1 text-2xl font-bold text-slate-950">{formatCute(balance?.credits || 0)}</div>
                    <div className="text-xs text-slate-500">${(balance?.credits_usd || 0).toFixed(2)} USD</div>
                  </div>
                  <div className="rounded-lg border border-emerald-100 bg-white p-4">
                    <div className="text-xs font-bold uppercase tracking-wide text-slate-500">API plan</div>
                    <div className="mt-1 text-2xl font-bold text-slate-950">{activeSubscription ? activePlan || 'active' : 'metered'}</div>
                    <div className="text-xs text-slate-500">{balance?.subscription_status || 'pay per request'}</div>
                  </div>
                </div>

                {apiKey && (
                  <div className="rounded-lg border border-pink-100 bg-white p-4">
                    <div className="mb-2 flex items-center justify-between gap-3">
                      <div className="flex items-center gap-2 text-sm font-bold text-slate-700">
                        <Key size={16} />
                        API key
                      </div>
                      <button onClick={copyApiKey} className="rounded-md p-2 text-slate-500 hover:bg-slate-100" aria-label="Copy API key">
                        {copied ? <Check size={16} className="text-emerald-600" /> : <Copy size={16} />}
                      </button>
                    </div>
                    <div className="overflow-hidden rounded-md bg-slate-950 px-3 py-2 font-mono text-xs text-slate-100">
                      {apiKey}
                    </div>
                  </div>
                )}
              </div>
            )}

            {status && <div className={`mt-5 rounded-lg border px-3 py-2 text-sm font-medium ${statusTone(status)}`}>{status}</div>}
          </div>

          {signedIn && (
            <div className="rounded-lg border border-amber-100 bg-white/95 p-5 shadow-sm shadow-amber-100/40 sm:p-6">
              <div className="mb-4 flex items-center gap-2">
                <Zap size={18} className="text-amber-500" />
                <h2 className="font-fredoka text-2xl font-bold">Auto top-up</h2>
              </div>
              <div className="space-y-4">
                <button
                  type="button"
                  onClick={() => setAutotopupEnabled(!autotopupEnabled)}
                  className={`flex w-full items-center justify-between rounded-lg border p-4 text-left ${autotopupEnabled ? 'border-emerald-300 bg-emerald-50' : 'border-pink-100 bg-slate-50'}`}
                  aria-pressed={autotopupEnabled}
                >
                  <span>
                    <span className="block text-sm font-bold text-slate-800">{autotopupEnabled ? 'Enabled' : 'Disabled'}</span>
                    <span className="block text-xs text-slate-500">Charge your saved Stripe card when credits run low.</span>
                  </span>
                  <span className={`h-6 w-11 rounded-full p-1 ${autotopupEnabled ? 'bg-emerald-500' : 'bg-slate-300'}`}>
                    <span className={`block h-4 w-4 rounded-full bg-white transition-transform ${autotopupEnabled ? 'translate-x-5' : ''}`} />
                  </span>
                </button>
                <div className="grid grid-cols-2 gap-3">
                  <label className="text-xs font-bold text-slate-600">
                    Threshold USD
                    <input value={autotopupThreshold} onChange={(e) => setAutotopupThreshold(e.target.value)} type="number" min="1" max="100" className="mt-1 w-full rounded-lg border border-pink-100 px-3 py-2 text-sm font-normal outline-none focus:border-pink-400" />
                  </label>
                  <label className="text-xs font-bold text-slate-600">
                    Top-up USD
                    <input value={autotopupAmount} onChange={(e) => setAutotopupAmount(e.target.value)} type="number" min="5" max="500" className="mt-1 w-full rounded-lg border border-pink-100 px-3 py-2 text-sm font-normal outline-none focus:border-pink-400" />
                  </label>
                </div>
                <button onClick={saveAutotopup} disabled={autotopupSaving} className="w-full rounded-lg bg-slate-950 px-4 py-3 text-sm font-bold text-white disabled:opacity-50">
                  {autotopupSaving ? 'Saving...' : 'Save auto top-up'}
                </button>
                {balance && !balance.has_payment_method && (
                  <div className="rounded-lg bg-amber-50 px-3 py-2 text-xs font-medium text-amber-700">
                    Buy credits with Stripe once before enabling auto top-up.
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        <div className="space-y-6">
          <div className="rounded-lg border border-pink-100 bg-white/95 p-5 shadow-sm shadow-pink-100/40 sm:p-6">
            <div className="mb-5 flex items-start justify-between gap-4">
              <div>
                <h2 className="font-fredoka text-3xl font-bold">Checkout</h2>
                <p className="mt-1 text-sm text-slate-600">Subscribe for API access or buy metered credits.</p>
              </div>
              <CreditCard className="text-pink-500" size={24} />
            </div>

            {!signedIn ? (
              <div className="rounded-lg border border-dashed border-pink-200 bg-pink-50/40 p-8 text-center">
                <p className="text-sm font-medium text-slate-600">Login first to create a Stripe checkout tied to your account.</p>
              </div>
            ) : embeddedSecret ? (
              <div className="rounded-lg border border-pink-100 bg-white p-3" data-testid="embedded-checkout-container">
                <div className="mb-3 flex items-center justify-between px-1">
                  <div>
                    <div className="text-sm font-bold text-slate-800">Secure Stripe checkout</div>
                    <div className="text-xs text-slate-500">Plan: {checkoutKind}</div>
                  </div>
                  <button onClick={() => setEmbeddedSecret('')} className="rounded-md p-2 text-slate-500 hover:bg-slate-100" aria-label="Close checkout">
                    <X size={16} />
                  </button>
                </div>
                <div ref={checkoutElementRef} className="min-h-[520px]" />
              </div>
            ) : (
              <div className="grid gap-4 lg:grid-cols-3">
                <div className={`rounded-lg border p-5 ${activePlan === 'monthly' ? 'border-emerald-300 bg-emerald-50' : 'border-pink-100 bg-white'}`}>
                  <div className="mb-3 flex items-center justify-between">
                    <h3 className="text-lg font-bold">Monthly</h3>
                    {activePlan === 'monthly' && <Check size={18} className="text-emerald-600" />}
                  </div>
                  <div className="mb-1 text-3xl font-bold">$12</div>
                  <div className="mb-5 text-sm text-slate-500">per month</div>
                  <button onClick={() => startCheckout('monthly')} disabled={checkoutLoading} className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-slate-950 px-4 py-3 text-sm font-bold text-white hover:bg-slate-800 disabled:opacity-50">
                    Choose <ArrowRight size={16} />
                  </button>
                </div>

                <div className={`rounded-lg border p-5 ${activePlan === 'annual' ? 'border-emerald-300 bg-emerald-50' : 'border-pink-100 bg-white'}`}>
                  <div className="mb-3 flex items-center justify-between">
                    <h3 className="text-lg font-bold">Annual</h3>
                    <Sparkles size={18} className="text-pink-500" />
                  </div>
                  <div className="mb-1 text-3xl font-bold">$120</div>
                  <div className="mb-5 text-sm text-slate-500">per year</div>
                  <button onClick={() => startCheckout('annual')} disabled={checkoutLoading} className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-pink-600 px-4 py-3 text-sm font-bold text-white disabled:opacity-50">
                    Choose <ArrowRight size={16} />
                  </button>
                </div>

                <div className="rounded-lg border border-pink-100 bg-white p-5">
                  <h3 className="mb-3 text-lg font-bold">Credits</h3>
                  <label className="mb-3 block text-xs font-bold text-slate-600">
                    Amount USD
                    <div className="relative mt-1">
                      <span className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400">$</span>
                      <input value={creditsAmount} onChange={(e) => setCreditsAmount(e.target.value)} type="number" min="1" max="500" className="w-full rounded-lg border border-pink-100 py-3 pl-7 pr-3 text-base outline-none focus:border-pink-400" />
                    </div>
                  </label>
                  <button onClick={() => startCheckout('credits')} disabled={checkoutLoading} className="inline-flex w-full items-center justify-center gap-2 rounded-lg border border-pink-200 bg-white px-4 py-3 text-sm font-bold text-slate-900 hover:border-pink-400 hover:bg-pink-50 disabled:opacity-50">
                    Buy credits <ArrowRight size={16} />
                  </button>
                  {balance?.cute_price_usd ? (
                    <p className="mt-3 text-xs text-slate-500">
                      About {formatCute(parseFloat(creditsAmount || '0') / balance.cute_price_usd)} CUTEDSL credits.
                    </p>
                  ) : null}
                </div>
              </div>
            )}
          </div>

          {testMode && (
            <div className="fixed right-4 top-4 z-50 w-[min(24rem,calc(100vw-2rem))] rounded-lg border border-slate-700 bg-slate-950 p-4 text-white shadow-2xl" data-testid="account-self-test">
              <div className="mb-3 flex items-center justify-between gap-3">
                <div>
                  <div className="text-sm font-bold text-emerald-300">Account E2E</div>
                  <div className="text-xs text-slate-400">signup, logout, login, reset, checkout</div>
                </div>
                <button
                  type="button"
                  onClick={runAccountSelfTest}
                  className="rounded-md border border-slate-700 px-2 py-1 text-xs font-bold text-slate-200 hover:bg-slate-800"
                >
                  Rerun
                </button>
              </div>
              <div className="space-y-1">
                {accountTestResults.length === 0 ? (
                  <div className="text-xs text-slate-400">Starting...</div>
                ) : (
                  accountTestResults.map((result) => (
                    <div
                      key={result.step}
                      data-testid={`account-test-${result.step.replace(/\s+/g, '-')}`}
                      className="grid grid-cols-[1fr_auto] gap-3 border-t border-slate-800 py-1.5 text-xs"
                    >
                      <span className="font-mono text-slate-200">{result.step}</span>
                      <span data-testid={`account-test-${result.step.replace(/\s+/g, '-')}-status`} className={
                        result.status === 'failed' ? 'text-red-300' :
                        result.status === 'running' ? 'text-amber-300' :
                        result.status === 'skipped' ? 'text-slate-400' :
                        'text-emerald-300'
                      }>
                        {result.status}
                      </span>
                      {result.detail && <span className="col-span-2 truncate text-slate-500">{result.detail}</span>}
                    </div>
                  ))
                )}
              </div>
            </div>
          )}

          <div className="rounded-lg border border-pink-100 bg-white/95 p-5 shadow-sm shadow-pink-100/40 sm:p-6">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="font-fredoka text-2xl font-bold">Recent activity</h2>
              {walletAddress && (
                <button onClick={() => refreshAccount(walletAddress)} className="rounded-md p-2 text-slate-500 hover:bg-slate-100" aria-label="Refresh account">
                  <RefreshCw size={16} />
                </button>
              )}
            </div>
            {events.length === 0 ? (
              <div className="rounded-lg bg-slate-50 p-6 text-sm text-slate-500">No billing events yet.</div>
            ) : (
              <div className="divide-y divide-slate-100">
                {events.slice(0, 12).map((event) => (
                  <div key={event.id} className="flex items-center justify-between gap-4 py-3">
                    <div className="min-w-0">
                      <div className="truncate text-sm font-medium text-slate-800">{event.description || event.event_type}</div>
                      <div className="text-xs text-slate-500">{new Date(event.created_at).toLocaleString()}</div>
                    </div>
                    <div className={`shrink-0 text-sm font-bold ${event.amount >= 0 ? 'text-emerald-700' : 'text-red-600'}`}>
                      {event.amount >= 0 ? '+' : '-'}{formatCute(Math.abs(event.amount))}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </section>
    </main>
  );
}
