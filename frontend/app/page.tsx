'use client';

import { browserStorage } from '@/lib/browser-storage';

import { useState, useEffect, useCallback, useRef } from 'react';
import {
  Sparkles, Wand2, Image as ImageIcon, LineChart, Coins, Heart, Zap,
  Mic, Volume2, BookOpen, Cloud, Code, Globe, Cpu, Database, Layout, Search, Gamepad2, Users,
  Wallet, ArrowRight, RefreshCw, Copy, Check, LogOut, X, Key, Mail, Eye, EyeOff, CreditCard, Menu,
  Video, Upload, ShieldCheck, LockKeyhole, ChevronDown
} from 'lucide-react';
import Image from 'next/image';
import Link from 'next/link';
import { CodeBlock } from '@/lib/code-block';
import { parseJSONResponse as parseHTTPJSONResponse, HTTPResponseError } from '@/lib/http';
import { uploadToBucket } from '@/lib/uploads';
import { STATIC_BASE_URL } from '@/lib/static-assets';
import { SiteFooter } from './site-footer';

const API_BASE = '/api';
const IMG_BASE = `${STATIC_BASE_URL}/images`;
const VIDEO_BASE = `${STATIC_BASE_URL}/videos`;

const NAV_LINKS: { href: string; label: string; hover: string }[] = [
  { href: '/tools', label: 'Creator Tools', hover: 'hover:text-purple-500' },
  { href: '/gallery', label: 'Gallery', hover: 'hover:text-pink-500' },
  { href: '#models', label: 'Models', hover: 'hover:text-pink-500' },
  { href: '/docs', label: 'API', hover: 'hover:text-blue-500' },
  { href: '#credits', label: 'Pricing', hover: 'hover:text-purple-500' },
];

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

declare global {
  interface Window {
    Stripe?: (publishableKey: string) => StripeBrowserClient;
  }
}

let stripeJsPromise: Promise<void> | null = null;

const loadStripeJS = () => {
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
};

interface WalletBalance {
  wallet_address: string;
  credits: number;
  credits_usd: number;
  cute_price_usd: number;
  total_deposited: number;
  autotopup_enabled?: boolean;
  autotopup_threshold_usd?: number;
  autotopup_amount_usd?: number;
  has_payment_method?: boolean;
  has_password?: boolean;
}

interface ServicePricing {
  service: string;
  price_usd: number;
  price_cute: number;
  cute_price_usd: number;
  unit: string;
}

interface BillingEvent {
  id: string;
  event_type: string;
  amount: number;
  cute_amount: number;
  usd_amount: number;
  description: string;
  credits_after: number;
  created_at: string;
}

interface UserPayload {
  id: string;
  wallet_address: string;
  email?: string;
  api_key?: string;
}

interface AuthResponse {
  user: UserPayload;
  api_key: string;
}

interface EmailUpdateResponse {
  success: boolean;
  email: string;
  has_password?: boolean;
  user?: UserPayload;
}

const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

const isValidEmail = (value: string) => emailPattern.test(value.trim());

async function parseJSONResponse<T>(res: Response, fallback: string): Promise<T> {
  return parseHTTPJSONResponse<T>(res, fallback);
}

export default function Home() {
  const [walletAddress, setWalletAddress] = useState<string | null>(null);
  const [balance, setBalance] = useState<WalletBalance | null>(null);
  const [pricing, setPricing] = useState<ServicePricing[]>([]);
  const [cutePrice, setCutePrice] = useState(0);
  const [solPrice, setSolPrice] = useState(0);
  const [billingHistory, setBillingHistory] = useState<BillingEvent[]>([]);
  const [depositAmount, setDepositAmount] = useState('10');
  const [depositLoading, setDepositLoading] = useState(false);
  const [depositResult, setDepositResult] = useState<any>(null);
  const [copied, setCopied] = useState(false);
  const [connectingWallet, setConnectingWallet] = useState(false);
  const [apiKey, setApiKey] = useState<string | null>(null);
  const [demoPrompt, setDemoPrompt] = useState('a cute fairy in an enchanted forest, digital art, pastel colors');
  const [demoResult, setDemoResult] = useState<string | null>(null);
  const [demoLoading, setDemoLoading] = useState(false);
  const [creatorMode, setCreatorMode] = useState<'image' | 'video'>('image');
  const [creatorPrompt, setCreatorPrompt] = useState('A bioluminescent fox moving through a moonlit flower garden');
  const [creatorAspect, setCreatorAspect] = useState('16:9');
  const [creatorModel, setCreatorModel] = useState('auto-video');
  const [creatorReference, setCreatorReference] = useState<File | null>(null);
  const [creatorReferencePreview, setCreatorReferencePreview] = useState('');
  const [creatorLoading, setCreatorLoading] = useState(false);
  const [creatorStatus, setCreatorStatus] = useState<string | null>(null);
  const [creatorResult, setCreatorResult] = useState<{type: 'image' | 'video'; url: string} | null>(null);
  const [showConversionFlow, setShowConversionFlow] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [testMode, setTestMode] = useState(false);
  const [testResults, setTestResults] = useState<{route: string; status: string; ms: number}[]>([]);
  const [email, setEmail] = useState<string | null>(null);
  const [emailInput, setEmailInput] = useState('');
  const [passwordInput, setPasswordInput] = useState('');
  const [authLoading, setAuthLoading] = useState(false);
  const [authStatus, setAuthStatus] = useState<string | null>(null);
  const [emailSaving, setEmailSaving] = useState(false);
  const [emailSaved, setEmailSaved] = useState(false);
  const [buyTab, setBuyTab] = useState<'card' | 'buy' | 'deposit'>('card');
  const [buySolAmount, setBuySolAmount] = useState('0.1');
  const [buyQuote, setBuyQuote] = useState<any>(null);
  const [buyLoading, setBuyLoading] = useState(false);
  const [buyStatus, setBuyStatus] = useState<string | null>(null);
  const [stripeAmount, setStripeAmount] = useState('25');
  const [stripeLoading, setStripeLoading] = useState(false);
  const [stripeStatus, setStripeStatus] = useState<string | null>(null);
  const [stripePublishableKey, setStripePublishableKey] = useState('');
  const [embeddedCheckoutClientSecret, setEmbeddedCheckoutClientSecret] = useState('');
  const [autotopupEnabled, setAutotopupEnabled] = useState(false);
  const [autotopupThreshold, setAutotopupThreshold] = useState('5');
  const [autotopupAmount, setAutotopupAmount] = useState('25');
  const [autotopupSaving, setAutotopupSaving] = useState(false);
  const [showAccount, setShowAccount] = useState(false);
  const [showApiKey, setShowApiKey] = useState(false);
  const [clientOrigin, setClientOrigin] = useState('');
  const embeddedCheckoutElementRef = useRef<HTMLDivElement | null>(null);
  const conversionCheckoutElementRef = useRef<HTMLDivElement | null>(null);
  const embeddedCheckoutRef = useRef<StripeEmbeddedCheckout | null>(null);
  const pendingAutotopupRef = useRef(false);
  const persistAutotopupRef = useRef<(() => Promise<void>) | null>(null);

  useEffect(() => {
    setClientOrigin(window.location.origin);
  }, []);

  useEffect(() => {
    if (!creatorReference) {
      setCreatorReferencePreview('');
      return;
    }
    const preview = URL.createObjectURL(creatorReference);
    setCreatorReferencePreview(preview);
    return () => URL.revokeObjectURL(preview);
  }, [creatorReference]);

  const storeAuth = useCallback((user: UserPayload, key: string) => {
    setWalletAddress(user.wallet_address);
    setApiKey(key);
    setEmail(user.email || null);
    if (user.email) setEmailInput(user.email);
    browserStorage.setItem('cutedsl_wallet', user.wallet_address);
    browserStorage.setItem('cutedsl_api_key', key);
    if (user.email) browserStorage.setItem('cutedsl_email', user.email);
    else browserStorage.removeItem('cutedsl_email');
  }, []);

  const clearStoredAuth = useCallback(() => {
    setApiKey(null);
    setWalletAddress(null);
    setEmail(null);
    setBalance(null);
    setBillingHistory([]);
    browserStorage.removeItem('cutedsl_api_key');
    browserStorage.removeItem('cutedsl_wallet');
    browserStorage.removeItem('cutedsl_email');
  }, []);

  // A key that no longer resolves to an account (rotated, or created against a
  // different environment) otherwise leaves the UI looking signed in while every
  // request fails with "invalid API key".
  const handleExpiredSession = useCallback((message?: string) => {
    clearStoredAuth();
    setAuthStatus(message || 'Your session expired. Sign in again to keep creating.');
    setShowConversionFlow(true);
  }, [clearStoredAuth]);

  // Fetch pricing on mount
  useEffect(() => {
    fetch(`${API_BASE}/pricing`)
      .then(r => r.json())
      .then(data => {
        setPricing(data.pricing || []);
        setCutePrice(data.cute_price_usd || 0);
        setSolPrice(data.sol_price_usd || 0);
      })
      .catch(() => {});
  }, []);

  // Fetch balance when wallet connected
  const fetchBalance = useCallback(async (wallet: string) => {
    try {
      const res = await fetch(`${API_BASE}/balance?wallet=${encodeURIComponent(wallet)}`);
      const data = await res.json();
      setBalance(data);
      setCutePrice(data.cute_price_usd || cutePrice);
      setAutotopupEnabled(!!data.autotopup_enabled);
      if (data.autotopup_threshold_usd) setAutotopupThreshold(String(data.autotopup_threshold_usd));
      if (data.autotopup_amount_usd) setAutotopupAmount(String(data.autotopup_amount_usd));
    } catch {}
  }, [cutePrice]);

  const fetchHistory = useCallback(async (wallet: string) => {
    try {
      const res = await fetch(`${API_BASE}/billing-history?wallet=${encodeURIComponent(wallet)}`);
      const data = await res.json();
      setBillingHistory(data.events || []);
    } catch {}
  }, []);

  useEffect(() => {
    const checkoutTarget = showConversionFlow ? conversionCheckoutElementRef.current : embeddedCheckoutElementRef.current;
    if (!embeddedCheckoutClientSecret || !stripePublishableKey || !checkoutTarget) return;

    let cancelled = false;
    const mountCheckout = async () => {
      try {
        embeddedCheckoutRef.current?.destroy();
        embeddedCheckoutRef.current = null;

        await loadStripeJS();
        if (cancelled) return;
        const stripe = window.Stripe?.(stripePublishableKey);
        if (!stripe) throw new Error('Stripe.js did not initialize');

        const checkout = await stripe.initEmbeddedCheckout({
          clientSecret: embeddedCheckoutClientSecret,
          onComplete: () => {
            setStripeStatus('Payment complete. Your credits will appear shortly.');
            setEmbeddedCheckoutClientSecret('');
            if (walletAddress) {
              fetchBalance(walletAddress);
              fetchHistory(walletAddress);
            }
            if (pendingAutotopupRef.current) {
              pendingAutotopupRef.current = false;
              window.setTimeout(() => persistAutotopupRef.current?.(), 1500);
            }
          },
        });
        if (cancelled) {
          checkout.destroy();
          return;
        }
        embeddedCheckoutRef.current = checkout;
        checkout.mount(checkoutTarget);
        setStripeStatus(null);
      } catch (err: any) {
        setStripeStatus(err?.message || 'Failed to load embedded Stripe checkout');
        setEmbeddedCheckoutClientSecret('');
      }
    };

    mountCheckout();

    return () => {
      cancelled = true;
      embeddedCheckoutRef.current?.destroy();
      embeddedCheckoutRef.current = null;
    };
  }, [embeddedCheckoutClientSecret, stripePublishableKey, walletAddress, fetchBalance, fetchHistory, showConversionFlow]);

  useEffect(() => {
    if (walletAddress) {
      fetchBalance(walletAddress);
      fetchHistory(walletAddress);
      const interval = setInterval(() => fetchBalance(walletAddress), 30000);
      return () => clearInterval(interval);
    }
  }, [walletAddress, fetchBalance, fetchHistory]);

  // Restore wallet and API key from localStorage
  useEffect(() => {
    const saved = browserStorage.getItem('cutedsl_wallet');
    if (saved) setWalletAddress(saved);
    const savedKey = browserStorage.getItem('cutedsl_api_key');
    if (savedKey) setApiKey(savedKey);
    const savedEmail = browserStorage.getItem('cutedsl_email');
    if (savedEmail) setEmail(savedEmail);
    // Confirm the stored key still belongs to an account. Only a 401 clears it —
    // a network blip must not sign the user out.
    if (savedKey) {
      fetch(`${API_BASE}/auth/session`, { headers: { Authorization: `Bearer ${savedKey}` } })
        .then(async (res) => {
          if (res.status === 401) {
            handleExpiredSession('Your saved API key no longer works. Sign in again to restore access.');
            return;
          }
          if (!res.ok) return;
          const data = await res.json() as AuthResponse;
          if (data?.user) storeAuth(data.user, data.api_key || savedKey);
        })
        .catch(() => {});
    }
    // ?test=true triggers e2e API test
    if (typeof window !== 'undefined' && new URLSearchParams(window.location.search).get('test') === 'true') {
      setTestMode(true);
      runE2ETests();
    }
    if (typeof window !== 'undefined') {
      const payment = new URLSearchParams(window.location.search).get('payment');
      if (payment === 'success') setStripeStatus('Payment received. Your credits will appear shortly.');
      if (payment === 'cancel') setStripeStatus('Checkout was cancelled.');
    }
  }, []);

  const signedIn = !!walletAddress && !!apiKey;
  const hasSolanaWallet = !!walletAddress && !walletAddress.startsWith('email:');
  const cardCheckoutReady = signedIn && !!email && !!balance?.has_password;

  const runE2ETests = async () => {
    const results: {route: string; status: string; ms: number}[] = [];
    const test = async (route: string, opts?: RequestInit, expectAuthed = false) => {
      const t0 = Date.now();
      try {
        const res = await fetch(`${API_BASE}${route}`, opts);
        const ms = Date.now() - t0;
        const ok = res.status < 500 && !(expectAuthed && res.status === 401);
        results.push({ route, status: ok ? `${res.status} OK` : `${res.status} FAIL`, ms });
        if (expectAuthed && res.status === 401) handleExpiredSession('Your saved API key no longer works. Sign in again to restore access.');
      } catch (e) {
        results.push({ route, status: 'ERR', ms: Date.now() - t0 });
      }
      setTestResults([...results]);
    };
    await test('/health');
    await test('/pricing');
    await test('/cute-price');
    await test('/balance?wallet=test_e2e_wallet');
    await test('/billing-history?wallet=test_e2e_wallet');
    await test('/auth/wallet', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({wallet_address: 'e2e_test_' + Date.now()}) });
    await test('/service', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({service:'zimage',wallet_address:'nonexistent'}) });
    const storedKey = browserStorage.getItem('cutedsl_api_key');
    if (storedKey) {
      await test('/auth/session', { headers: { Authorization: `Bearer ${storedKey}` } }, true);
    }
  };

  const loginWithEmailPassword = async () => {
    if (!isValidEmail(emailInput) || passwordInput.length < 8) {
      setAuthStatus('Enter a valid email and an 8+ character password.');
      return null;
    }

    setAuthLoading(true);
    setAuthStatus(null);
    try {
      const res = await fetch(`${API_BASE}/auth/email-login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: emailInput.trim(), password: passwordInput }),
      });
      const data = await parseJSONResponse<AuthResponse>(res, 'Email login failed');
      storeAuth(data.user, data.api_key);
      setBalance((current) => current ? { ...current, wallet_address: data.user.wallet_address, has_password: true } : {
        wallet_address: data.user.wallet_address,
        credits: 0,
        credits_usd: 0,
        cute_price_usd: cutePrice,
        total_deposited: 0,
        has_password: true,
      });
      setAuthStatus('Signed in with email. Card checkout is ready.');
      fetchBalance(data.user.wallet_address);
      fetchHistory(data.user.wallet_address);
      return data.user.wallet_address;
    } catch (err: any) {
      setAuthStatus(err?.message || 'Email login failed');
      return null;
    } finally {
      setAuthLoading(false);
    }
  };

  const tryImageGen = async () => {
    if (!apiKey) return;
    setDemoLoading(true);
    setDemoResult(null);
    try {
      const res = await fetch(`${API_BASE}/service`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${apiKey}` },
        body: JSON.stringify({ prompt: demoPrompt, width: 512, height: 512, num_steps: 8 }),
      });
      if (res.status === 401) {
        handleExpiredSession();
        return;
      }
      const data = await parseJSONResponse<any>(res, 'Failed to generate image');
      if (data.result?.image_base64) {
        setDemoResult(`data:image/webp;base64,${data.result.image_base64}`);
      } else {
        alert(data.error || JSON.stringify(data));
      }
    } catch (e) {
      alert('Failed to generate image');
    } finally {
      setDemoLoading(false);
    }
  };

  const uploadCreatorReference = async (file: File) => {
    if (!apiKey) throw new Error('Create an account before uploading a reference image.');
    try {
      return await uploadToBucket(file, {
        apiKey,
        dataset: 'video-sources',
        filename: file.name || 'reference.webp',
        contentType: file.type || 'image/webp',
        onProgress: pct => setCreatorStatus(`Uploading reference image… ${pct}%`),
      });
    } catch (err) {
      if (err instanceof HTTPResponseError && err.status === 401) {
        handleExpiredSession();
        throw new Error('Your session expired. Sign in again to upload a reference image.');
      }
      throw err;
    }
  };

  const createStudioAsset = async () => {
    if (!creatorPrompt.trim()) {
      setCreatorStatus('Describe what you want to create first.');
      return;
    }
    if (!signedIn || !apiKey) {
      setCreatorStatus(null);
      setShowConversionFlow(true);
      return;
    }
    if (creatorMode === 'video' && !creatorReference && creatorModel === 'ltx-2.3-image-to-video') {
      setCreatorStatus('Add a still image for the LTX 2.3 image-to-video model.');
      return;
    }

    setCreatorLoading(true);
    setCreatorStatus(creatorMode === 'video' ? 'Preparing your AV1 video… this can take a few minutes.' : 'Creating your image…');
    setCreatorResult(null);
    try {
      const dimensions: Record<string, [number, number]> = {
        '1:1': [1024, 1024],
        '16:9': [1024, 576],
        '9:16': [576, 1024],
        '4:3': [1024, 768],
      };
      const [width, height] = dimensions[creatorAspect] || dimensions['16:9'];
      let imageURL = '';
      if (creatorMode === 'video' && creatorReference) {
        imageURL = await uploadCreatorReference(creatorReference);
      }
      const payload = creatorMode === 'image'
        ? { service: 'zimage', prompt: creatorPrompt.trim(), width, height, num_steps: 8 }
        : {
            service: 'video_generate',
            model: creatorModel,
            prompt: creatorPrompt.trim(),
            image_url: imageURL || undefined,
            aspect_ratio: creatorAspect,
            duration: 5,
            output_format: 'webm',
          };
      const res = await fetch(`${API_BASE}/service`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${apiKey}` },
        body: JSON.stringify(payload),
      });
      if (res.status === 401) {
        handleExpiredSession();
        return;
      }
      const data = await parseJSONResponse<any>(res, `Could not create ${creatorMode}`);
      if (creatorMode === 'image') {
        const imageURLResult = data.result?.image_url || data.saved_image?.url || (data.result?.image_base64 ? `data:image/webp;base64,${data.result.image_base64}` : '');
        if (!imageURLResult) throw new Error('The image finished without a displayable result.');
        setCreatorResult({ type: 'image', url: imageURLResult });
      } else {
        const videoURL = data.result?.video_url || data.result?.result?.video_url;
        if (!videoURL) throw new Error('The video finished without a displayable result.');
        setCreatorResult({ type: 'video', url: videoURL });
      }
      setCreatorStatus('Ready — your creation is saved at its original aspect ratio.');
      if (walletAddress) fetchBalance(walletAddress);
    } catch (err: any) {
      const message = err?.message || `Could not create ${creatorMode}`;
      setCreatorStatus(message);
      if (/credit|payment|402/i.test(message)) setShowConversionFlow(true);
    } finally {
      setCreatorLoading(false);
    }
  };

  const continueCreatorSignup = async () => {
    const wallet = await loginWithEmailPassword();
    if (wallet) {
      setCreatorStatus('Account ready. Add credits, then create.');
    }
  };

  const connectWallet = async () => {
    setConnectingWallet(true);
    setAuthStatus(null);
    try {
      // Check for Phantom wallet
      const solana = (window as any).solana;
      const registerWallet = async (addr: string) => {
        const res = await fetch(`${API_BASE}/auth/wallet`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            wallet_address: addr,
            api_key: apiKey || undefined,
            email: isValidEmail(emailInput) ? emailInput.trim() : undefined,
            password: passwordInput.length >= 8 ? passwordInput : undefined,
          }),
        });
        const data = await parseJSONResponse<AuthResponse>(res, 'Wallet login failed');
        storeAuth(data.user, data.api_key);
        fetchBalance(data.user.wallet_address);
        fetchHistory(data.user.wallet_address);
        setAuthStatus(data.user.email ? 'Wallet connected to your email account.' : 'Wallet connected.');
      };

      if (solana?.isPhantom) {
        const resp = await solana.connect();
        const addr = resp.publicKey.toString();
        await registerWallet(addr);
      } else {
        // Fallback: prompt for wallet address
        const addr = prompt('Enter your Solana wallet address:');
        if (addr && addr.length > 30) {
          await registerWallet(addr);
        }
      }
    } catch (err: any) {
      setAuthStatus(err?.message || 'Wallet connect failed');
      console.error('Wallet connect error:', err);
    } finally {
      setConnectingWallet(false);
    }
  };

  const disconnectWallet = () => {
    setWalletAddress(null);
    setBalance(null);
    setBillingHistory([]);
    setApiKey(null);
    setEmail(null);
    setEmailInput('');
    setPasswordInput('');
    setAuthStatus(null);
    setEmailSaved(false);
    browserStorage.removeItem('cutedsl_wallet');
    browserStorage.removeItem('cutedsl_api_key');
    browserStorage.removeItem('cutedsl_email');
    try {
      const solana = (window as any).solana;
      if (solana?.isPhantom) solana.disconnect();
    } catch {}
  };

  const saveEmail = async () => {
    if (!walletAddress || !isValidEmail(emailInput)) return false;
    setEmailSaving(true);
    setAuthStatus(null);
    try {
      const payload: Record<string, unknown> = {
        wallet_address: walletAddress,
        email: emailInput.trim(),
      };
      if (passwordInput.length >= 8) {
        payload.password = passwordInput;
      }
      const res = await fetch(`${API_BASE}/auth/email`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await parseJSONResponse<EmailUpdateResponse>(res, 'Failed to save email login');
      if (data.success) {
        setEmail(data.email);
        setEmailInput(data.email);
        browserStorage.setItem('cutedsl_email', data.email);
        if (data.has_password) {
          setBalance((current) => current ? { ...current, has_password: true } : current);
        }
        setEmailSaved(true);
        setAuthStatus(data.has_password ? 'Email and password saved for card checkout.' : 'Email saved.');
        setTimeout(() => setEmailSaved(false), 3000);
        return true;
      }
    } catch (err: any) {
      setAuthStatus(err?.message || 'Failed to save email login');
      console.error('Email save error:', err);
      return false;
    } finally {
      setEmailSaving(false);
    }
    return false;
  };

  const createDeposit = async () => {
    if (!hasSolanaWallet || !walletAddress || !depositAmount) {
      setBuyStatus('Connect a Solana wallet before depositing tokens.');
      return;
    }
    setDepositLoading(true);
    setDepositResult(null);
    try {
      const res = await fetch(`${API_BASE}/crypto-checkout`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          wallet_address: walletAddress,
          method: 'cute',
          amount: parseFloat(depositAmount),
        }),
      });
      const data = await res.json();
      if (res.ok) {
        setDepositResult(data);
        // Start listening for payment
        const es = new EventSource(`${API_BASE}/crypto-checkout/${data.intent_id}/events`);
        es.onmessage = (event) => {
          const parsed = JSON.parse(event.data);
          if (parsed.status === 'paid') {
            es.close();
            setDepositResult(null);
            fetchBalance(walletAddress);
            fetchHistory(walletAddress);
          }
        };
      } else {
        alert(data.error || 'Deposit failed');
      }
    } catch (err) {
      alert('Failed to create deposit');
    } finally {
      setDepositLoading(false);
    }
  };

  const ensureStripeBillingAccount = async () => {
    if (!signedIn || !walletAddress) {
      setStripeStatus('Create or login with email before card checkout.');
      return null;
    }

    if (!email || !isValidEmail(email)) {
      setStripeStatus('Save an email before card checkout.');
      return null;
    }
    if (!balance?.has_password) {
      setStripeStatus('Save an 8+ character password before card checkout.');
      return null;
    }
    return walletAddress;
  };

  const createStripeCheckout = async (amountUsd?: number) => {
    if (!stripeAmount && !amountUsd) return false;
    setStripeLoading(true);
    setStripeStatus(null);
    try {
      const billingWallet = await ensureStripeBillingAccount();
      if (!billingWallet) return false;
      const amount = amountUsd ?? parseFloat(stripeAmount);
      const res = await fetch(`${API_BASE}/stripe-checkout`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          wallet_address: billingWallet,
          amount_usd: amount,
          return_url: `${window.location.origin}/?payment=success&session_id={CHECKOUT_SESSION_ID}#credits`,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.error || 'Failed to start Stripe checkout');
      }
      if (data.client_secret && data.publishable_key) {
        setStripePublishableKey(data.publishable_key);
        setEmbeddedCheckoutClientSecret(data.client_secret);
        setStripeStatus(null);
        return true;
      }
      if (data.url) {
        window.location.href = data.url;
        return true;
      }
      throw new Error('Stripe checkout response did not include a client secret');
    } catch (err: any) {
      setStripeStatus(err?.message || 'Stripe checkout failed');
      return false;
    } finally {
      setStripeLoading(false);
    }
  };

  const createSubscriptionCheckout = async (plan: 'monthly' | 'annual') => {
    setStripeLoading(true);
    setStripeStatus(null);
    try {
      const billingWallet = await ensureStripeBillingAccount();
      if (!billingWallet) return false;
      const res = await fetch(`${API_BASE}/stripe-checkout`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          wallet_address: billingWallet,
          type: 'subscription',
          plan,
          return_url: `${window.location.origin}/?payment=success&session_id={CHECKOUT_SESSION_ID}#credits`,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed to start subscription checkout');
      if (!data.client_secret || !data.publishable_key) throw new Error('Stripe checkout response did not include a client secret');
      setStripePublishableKey(data.publishable_key);
      setEmbeddedCheckoutClientSecret(data.client_secret);
      return true;
    } catch (err: any) {
      setStripeStatus(err?.message || 'Subscription checkout failed');
      return false;
    } finally {
      setStripeLoading(false);
    }
  };

  const persistAutotopupSettings = async () => {
    if (!walletAddress) return;
    setAutotopupSaving(true);
    try {
      const res = await fetch(`${API_BASE}/autotopup-settings`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          wallet_address: walletAddress,
          enabled: autotopupEnabled,
          threshold_usd: parseFloat(autotopupThreshold || '5'),
          amount_usd: parseFloat(autotopupAmount || '25'),
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed to save auto top-up');
      setAutotopupEnabled(!!data.enabled);
      setAutotopupThreshold(String(data.threshold_usd || 5));
      setAutotopupAmount(String(data.amount_usd || 25));
      setStripeStatus(data.enabled ? 'Auto top-up enabled.' : 'Auto top-up disabled.');
      fetchBalance(walletAddress);
    } catch (err: any) {
      setStripeStatus(err?.message || 'Failed to save auto top-up');
    } finally {
      setAutotopupSaving(false);
    }
  };
  persistAutotopupRef.current = persistAutotopupSettings;

  const saveAutotopupSettings = async () => {
    if (!walletAddress) return;
    setStripeStatus(null);
    if (autotopupEnabled && !balance?.has_payment_method) {
      const amount = Math.min(500, Math.max(5, parseFloat(autotopupAmount || '25') || 25));
      pendingAutotopupRef.current = true;
      setStripeAmount(String(amount));
      const opened = await createStripeCheckout(amount);
      if (opened) setStripeStatus('Complete checkout to save a card; auto top-up turns on automatically.');
      else pendingAutotopupRef.current = false;
      return;
    }
    await persistAutotopupSettings();
  };

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const bytesToBase64 = (bytes: Uint8Array) => {
    let binary = '';
    const chunkSize = 0x8000;
    for (let i = 0; i < bytes.length; i += chunkSize) {
      binary += String.fromCharCode(...bytes.subarray(i, i + chunkSize));
    }
    return btoa(binary);
  };

  // Fetch swap quote from bags.fm via our proxy
  const fetchSwapQuote = async (solAmt: string) => {
    if (!solAmt || parseFloat(solAmt) <= 0) { setBuyQuote(null); return; }
    try {
      const res = await fetch(`${API_BASE}/swap/quote?sol_amount=${solAmt}`);
      const data = await res.json();
      if (data.success) setBuyQuote(data);
      else setBuyQuote(null);
    } catch { setBuyQuote(null); }
  };

  // Execute swap: get quote → build tx → sign with Phantom → send
  const executeBuy = async () => {
    if (!hasSolanaWallet || !walletAddress || !buySolAmount || buyLoading) {
      setBuyStatus('Connect a Solana wallet before buying with SOL.');
      return;
    }
    const solana = (window as any).solana;
    if (!solana?.isPhantom) {
      setBuyStatus('Phantom wallet required for swaps');
      return;
    }

    setBuyLoading(true);
    setBuyStatus('Getting quote...');
    try {
      // 1. Get fresh quote
      const quoteRes = await fetch(`${API_BASE}/swap/quote?sol_amount=${buySolAmount}`);
      const quoteData = await quoteRes.json();
      if (!quoteData.success) throw new Error('Failed to get quote');

      // 2. Build swap transaction
      setBuyStatus('Building transaction...');
      const swapRes = await fetch(`${API_BASE}/swap/transaction`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          quote: quoteData.quote,
          user_public_key: walletAddress,
        }),
      });
      const swapData = await swapRes.json();
      if (!swapData.success) throw new Error(swapData.error || 'Failed to build transaction');

      // 3. Deserialize and sign with Phantom
      setBuyStatus('Sign in your wallet...');
      const txData = swapData.transaction;
      const swapTxEncoded = txData.swapTransaction;

      // bags.fm returns base58-encoded VersionedTransaction
      const bs58 = await import('bs58');
      const { VersionedTransaction } = await import('@solana/web3.js');
      const txBytes = bs58.default.decode(swapTxEncoded);
      const transaction = VersionedTransaction.deserialize(txBytes);

      // Sign with Phantom, then broadcast through our backend RPC failover.
      const signed = await solana.signTransaction(transaction);
      setBuyStatus('Sending transaction...');

      const sendRes = await fetch(`${API_BASE}/swap/send_transaction`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ signed_transaction: bytesToBase64(signed.serialize()) }),
      });
      const sendData = await sendRes.json();
      if (!sendRes.ok || !sendData.success) {
        throw new Error(sendData.error || 'Failed to send transaction');
      }

      const signature = sendData.signature;

      setBuyStatus(sendData.confirmed
        ? `Swap complete! Tx: ${signature.slice(0, 8)}...`
        : `Swap submitted (${sendData.confirmation_status || 'pending'}): ${signature.slice(0, 8)}...`
      );
      setBuyQuote(null);

      // Refresh balance after a short delay
      setTimeout(() => {
        if (walletAddress) {
          fetchBalance(walletAddress);
          fetchHistory(walletAddress);
        }
      }, 3000);

    } catch (err: any) {
      const msg = err?.message || 'Swap failed';
      if (msg.includes('User rejected')) {
        setBuyStatus('Transaction cancelled');
      } else {
        setBuyStatus(`Error: ${msg}`);
      }
    } finally {
      setBuyLoading(false);
      setTimeout(() => setBuyStatus(null), 8000);
    }
  };

  const getServicePrice = (service: string) => {
    const p = pricing.find(p => p.service === service);
    return p ? p.price_cute : 0;
  };

  // USD fallbacks mirror server/services.go servicePricesUSD so cards show a
  // price before /pricing resolves (and if the backend is unreachable).
  const SERVICE_USD_FALLBACK: Record<string, number> = {
    zimage: 0.04, chronos2: 0.002, tts: 0.005, stt: 0.02,
    gemma4: 0.01, caption: 0.01, ltx_video: 0.30, h3_video: 2.688, flux_image: 0.04,
  };
  const getServiceUsd = (service: string) => {
    const p = pricing.find(p => p.service === service);
    return p && p.price_usd > 0 ? p.price_usd : (SERVICE_USD_FALLBACK[service] ?? 0);
  };

  const formatCute = (n: number) => {
    if (n >= 1000000) return `${(n / 1000000).toFixed(1)}M`;
    if (n >= 1000) return `${(n / 1000).toFixed(1)}K`;
    return n.toFixed(0);
  };

  const formatUsd = (n: number) => (n >= 0.01 ? `$${n.toFixed(2)}` : `$${n.toFixed(3)}`);

  return (
      <div className="min-h-screen overflow-hidden relative selection:bg-pink-300 selection:text-pink-900">
        {/* CSS-only background avoids React timers and extra LCP-network contention. */}
        <div className="fixed inset-0 -z-20 bg-[linear-gradient(135deg,#fff1f7_0%,#f5f3ff_48%,#ecfeff_100%)]" />

      {/* Navigation */}
      <header>
      <nav aria-label="Main navigation" className="w-full px-4 sm:px-8 py-5 flex justify-between items-center relative z-30">
        <Link href="/" className="flex items-center gap-2 shrink-0">
          <Image src={`${IMG_BASE}/logo.webp`} alt="CuteDSL" width={40} height={40} className="rounded-lg" />
          <span className="font-fredoka text-3xl font-bold text-pink-600 tracking-wide">CuteDSL</span>
        </Link>
        <div className="hidden lg:flex gap-5 font-bold text-slate-700">
          {NAV_LINKS.map((l) => (
            <Link key={l.href} href={l.href} className={`transition-colors ${l.hover}`}>{l.label}</Link>
          ))}
        </div>
        <div className="flex items-center gap-3">
          {signedIn ? (
            <div className="flex items-center gap-3">
              <Link href="/account" className="hidden sm:flex items-center gap-2 bg-white/90 px-4 py-2 rounded-full border border-pink-200 shadow-sm hover:shadow-md transition-all cursor-pointer">
                <Coins size={16} className="text-yellow-500" />
                <span className="font-bold text-slate-700">{balance ? formatCute(balance.credits) : '...'} $CUTEDSL</span>
                {balance && cutePrice > 0 && (
                  <span className="text-xs text-slate-400">(${(balance.credits * cutePrice).toFixed(2)})</span>
                )}
              </Link>
              <Link
                href="/account"
                className="flex items-center gap-2 bg-white/80 text-slate-600 font-bold px-4 py-2 rounded-full shadow-sm hover:shadow-md transition-all border border-slate-200 text-sm"
                title={walletAddress}
              >
                <Wallet size={16} />
                {email ? email.split('@')[0] : `${walletAddress.slice(0, 4)}...${walletAddress.slice(-4)}`}
              </Link>
            </div>
          ) : (
            <button
              type="button"
              aria-label="Start creating"
              onClick={() => setShowConversionFlow(true)}
              className="bg-slate-950 text-white font-bold px-4 sm:px-6 py-2.5 rounded-xl shadow-lg shadow-slate-900/10 hover:bg-slate-800 transition-colors flex items-center gap-2"
            >
              <Sparkles size={17} />
              <span className="hidden sm:inline">Start creating</span>
            </button>
          )}
          {/* Burger menu (small screens) */}
          <button
            type="button"
            aria-label="Toggle menu"
            aria-expanded={mobileMenuOpen}
            onClick={() => setMobileMenuOpen((o) => !o)}
            className="lg:hidden flex items-center justify-center w-10 h-10 rounded-full bg-white/90 border border-pink-200 shadow-sm text-slate-700 hover:text-pink-500 transition-colors"
          >
            {mobileMenuOpen ? <X size={22} /> : <Menu size={22} />}
          </button>
        </div>
      </nav>

      {/* Mobile menu drawer */}
      {mobileMenuOpen && (
        <div className="lg:hidden fixed inset-0 z-20" onClick={() => setMobileMenuOpen(false)}>
          <div className="absolute inset-0 bg-black/30" />
          <div
            className="absolute top-0 right-0 h-full w-72 max-w-[80vw] bg-white shadow-2xl p-6 pt-24 flex flex-col gap-1 overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
          >
            {NAV_LINKS.map((l) => (
              <Link
                key={l.href}
                href={l.href}
                onClick={() => setMobileMenuOpen(false)}
                className={`font-bold text-slate-700 text-lg py-3 px-3 rounded-xl hover:bg-pink-50 transition-colors ${l.hover}`}
              >
                {l.label}
              </Link>
            ))}
          </div>
        </div>
      )}
      </header>

      {/* Account Panel */}
      {showAccount && walletAddress && (
          <div
            className="fixed inset-0 z-50 bg-black/40 flex items-start justify-center pt-20 px-4"
            onClick={(e) => { if (e.target === e.currentTarget) setShowAccount(false); }}
          >
            <div
              className="bg-white rounded-3xl shadow-2xl w-full max-w-lg overflow-hidden"
            >
              {/* Header */}
              <div className="bg-gradient-to-r from-pink-400 to-purple-400 p-6 text-white relative">
                <button onClick={() => setShowAccount(false)} className="absolute top-4 right-4 p-1 hover:bg-white/20 rounded-lg transition-colors">
                  <X size={20} />
                </button>
                <div className="flex items-center gap-3 mb-3">
                  <div className="bg-white/20 p-2 rounded-full">
                    <Wallet size={24} />
                  </div>
                  <div>
                    <div className="font-bold text-lg">{email || 'My Account'}</div>
                    <div className="text-white/80 text-sm font-mono">{walletAddress.slice(0, 8)}...{walletAddress.slice(-6)}</div>
                  </div>
                </div>
                <div className="bg-white/20 rounded-2xl p-4 mt-2">
                  <div className="text-white/70 text-xs mb-1">Balance</div>
                  <div className="text-3xl font-fredoka font-bold">
                    {balance ? formatCute(balance.credits) : '...'} <span className="text-lg text-white/80">$CUTEDSL</span>
                  </div>
                  {balance && cutePrice > 0 && (
                    <div className="text-white/60 text-sm mt-1">&asymp; ${(balance.credits * cutePrice).toFixed(2)} USD</div>
                  )}
                </div>
              </div>

              <div className="p-6 space-y-5 max-h-[60vh] overflow-y-auto">
                {/* Email */}
                <div>
                  <label className="text-sm font-bold text-slate-600 mb-2 flex items-center gap-2"><Mail size={14} /> Email (optional)</label>
                  {!emailSaved ? (
                    <div className="flex gap-2">
                      <input
                        type="email"
                        value={emailInput}
                        onChange={(e) => setEmailInput(e.target.value)}
                        className="flex-1 px-4 py-2 rounded-xl border border-slate-200 focus:border-pink-400 focus:ring-2 focus:ring-pink-200 outline-none text-sm"
                        placeholder="you@example.com"
                      />
                      <button
                        onClick={saveEmail}
                        disabled={emailSaving || !emailInput}
                        className="bg-pink-500 text-white font-bold px-4 py-2 rounded-xl text-sm hover:bg-pink-600 transition-colors disabled:opacity-50"
                      >
                        {emailSaving ? <RefreshCw size={14} className="animate-spin" /> : 'Save'}
                      </button>
                    </div>
                  ) : (
                    <div className="flex items-center gap-2 text-sm text-slate-600 bg-green-50 px-4 py-2 rounded-xl">
                      <Check size={14} className="text-green-500" />
                      {email}
                    </div>
                  )}
                  <div className="text-xs text-slate-400 mt-1">Optional. We&apos;ll send onboarding tips about the API.</div>
                </div>

                {/* API Key */}
                {apiKey && (
                  <div>
                    <label className="text-sm font-bold text-slate-600 mb-2 flex items-center gap-2"><Key size={14} /> API Key</label>
                    <div className="flex items-center gap-2">
                      <div className="flex-1 bg-slate-50 border border-slate-200 rounded-xl px-4 py-2 font-mono text-sm overflow-hidden">
                        {showApiKey ? apiKey : `${apiKey.slice(0, 8)}${'•'.repeat(20)}`}
                      </div>
                      <button onClick={() => setShowApiKey(!showApiKey)} className="p-2 hover:bg-slate-100 rounded-lg text-slate-400" title={showApiKey ? 'Hide' : 'Show'}>
                        {showApiKey ? <EyeOff size={16} /> : <Eye size={16} />}
                      </button>
                      <button onClick={() => copyToClipboard(apiKey)} className="p-2 hover:bg-slate-100 rounded-lg text-slate-400" title="Copy">
                        {copied ? <Check size={16} className="text-green-500" /> : <Copy size={16} />}
                      </button>
                    </div>
                    <div className="text-xs text-slate-400 mt-1">Use as: <code className="bg-slate-100 px-1 rounded">Authorization: Bearer {'<key>'}</code></div>
                  </div>
                )}

                {/* Quick Actions */}
                <div className="grid grid-cols-2 gap-3">
                  <a href="#api" onClick={() => setShowAccount(false)} className="bg-slate-50 hover:bg-slate-100 p-3 rounded-xl text-center transition-colors">
                    <Coins size={20} className="text-yellow-500 mx-auto mb-1" />
                    <div className="text-sm font-bold text-slate-700">Add Credits</div>
                  </a>
                  <a href="#api-docs" onClick={() => setShowAccount(false)} className="bg-slate-50 hover:bg-slate-100 p-3 rounded-xl text-center transition-colors">
                    <Code size={20} className="text-blue-500 mx-auto mb-1" />
                    <div className="text-sm font-bold text-slate-700">API Docs</div>
                  </a>
                </div>

                {/* Recent Activity */}
                {billingHistory.length > 0 && (
                  <div>
                    <div className="text-sm font-bold text-slate-600 mb-2">Recent Activity</div>
                    <div className="space-y-1 max-h-32 overflow-y-auto">
                      {billingHistory.slice(0, 5).map(event => (
                        <div key={event.id} className="flex justify-between items-center text-sm py-1.5 px-3 bg-slate-50 rounded-lg">
                          <span className="text-slate-500 text-xs">{event.description}</span>
                          <span className={`font-bold text-xs ${event.amount >= 0 ? 'text-green-600' : 'text-red-500'}`}>
                            {event.amount >= 0 ? '+' : ''}{formatCute(Math.abs(event.amount))}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Disconnect */}
                <button
                  onClick={() => { disconnectWallet(); setShowAccount(false); }}
                  className="w-full flex items-center justify-center gap-2 text-slate-400 hover:text-red-500 py-3 border border-slate-200 rounded-xl hover:border-red-200 transition-colors text-sm font-bold"
                >
                  <LogOut size={16} />
                  Disconnect Wallet
                </button>
              </div>
            </div>
          </div>
        )}

      {showConversionFlow && (
        <div className="fixed inset-0 z-[70] flex items-start justify-center overflow-y-auto bg-slate-950/55 p-4 backdrop-blur-sm sm:items-center" onMouseDown={(event) => {
          if (event.target === event.currentTarget) {
            setShowConversionFlow(false);
            setEmbeddedCheckoutClientSecret('');
          }
        }}>
          <div className="relative my-2 w-full max-w-lg overflow-hidden rounded-[28px] border border-white/70 bg-white shadow-2xl sm:my-6">
            <button type="button" aria-label="Close signup and payment" onClick={() => { setShowConversionFlow(false); setEmbeddedCheckoutClientSecret(''); }} className="absolute right-4 top-4 z-10 rounded-full border border-slate-200 bg-white p-2 text-slate-500 hover:text-slate-900"><X size={18} /></button>
            <div className="border-b border-slate-100 bg-gradient-to-br from-pink-50 via-white to-violet-50 p-6 pr-14 sm:p-8">
              <h2 className="font-fredoka text-3xl font-bold text-slate-950 sm:text-4xl">Create, pay, then make it.</h2>
              <p className="mt-2 text-sm font-medium leading-relaxed text-slate-600">Sign up with your email and start creating.</p>
              <div className="mt-5 grid grid-cols-3 gap-2 text-center text-[11px] font-extrabold text-slate-500">
                <span className="rounded-xl bg-white px-2 py-2 ring-1 ring-slate-200">1 · Account</span>
                <span className="rounded-xl bg-white px-2 py-2 ring-1 ring-slate-200">2 · Card credits</span>
                <span className="rounded-xl bg-white px-2 py-2 ring-1 ring-slate-200">3 · Create</span>
              </div>
            </div>

            <div className="p-6 sm:p-8">
              {!signedIn ? (
                <div className="space-y-4">
                  <label className="block text-sm font-extrabold text-slate-700">Email
                    <input type="email" value={emailInput} onChange={(event) => setEmailInput(event.target.value)} data-testid="conversion-email" autoComplete="email" className="mt-1.5 w-full rounded-xl border border-slate-200 px-4 py-3 font-medium outline-none focus:border-pink-400 focus:ring-4 focus:ring-pink-100" placeholder="you@example.com" />
                  </label>
                  <label className="block text-sm font-extrabold text-slate-700">Password
                    <input type="password" value={passwordInput} onChange={(event) => setPasswordInput(event.target.value)} onKeyDown={(event) => event.key === 'Enter' && continueCreatorSignup()} data-testid="conversion-password" autoComplete="current-password" className="mt-1.5 w-full rounded-xl border border-slate-200 px-4 py-3 font-medium outline-none focus:border-pink-400 focus:ring-4 focus:ring-pink-100" placeholder="8+ characters" />
                  </label>
                  <button type="button" onClick={continueCreatorSignup} disabled={authLoading || !isValidEmail(emailInput) || passwordInput.length < 8} data-testid="conversion-continue" className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-slate-950 px-5 py-3.5 font-extrabold text-white hover:bg-slate-800 disabled:opacity-50">
                    {authLoading ? <RefreshCw className="animate-spin" size={18} /> : <ArrowRight size={18} />} Continue to secure payment
                  </button>
                  <p className="text-center text-xs font-bold text-slate-400">New here? This creates your account. Returning? It signs you in.</p>
                </div>
              ) : !cardCheckoutReady ? (
                <div className="space-y-4">
                  <div className="rounded-xl bg-emerald-50 px-4 py-3 text-sm font-bold text-emerald-700"><Check className="mr-2 inline" size={16} /> Account ready. Finish your email login.</div>
                  <input type="email" value={emailInput} onChange={(event) => setEmailInput(event.target.value)} className="w-full rounded-xl border border-slate-200 px-4 py-3" placeholder="you@example.com" />
                  <input type="password" value={passwordInput} onChange={(event) => setPasswordInput(event.target.value)} className="w-full rounded-xl border border-slate-200 px-4 py-3" placeholder="8+ character password" />
                  <button type="button" onClick={saveEmail} disabled={emailSaving || !isValidEmail(emailInput) || passwordInput.length < 8} className="w-full rounded-xl bg-slate-950 px-5 py-3.5 font-extrabold text-white disabled:opacity-50">Save and continue</button>
                </div>
              ) : embeddedCheckoutClientSecret ? (
                <div>
                  <div className="mb-3 flex items-center gap-2 text-sm font-extrabold text-slate-800"><LockKeyhole size={16} className="text-emerald-600" /> Checkout for {email}</div>
                  <div ref={conversionCheckoutElementRef} data-testid="conversion-stripe-checkout" className="min-h-[420px] overflow-hidden rounded-xl border border-slate-200" />
                </div>
              ) : (
                <div className="space-y-5">
                  <div className="rounded-xl bg-emerald-50 px-4 py-3 text-sm font-bold text-emerald-700"><Check className="mr-2 inline" size={16} /> Signed in as {email}</div>
                  <div>
                    <div className="mb-2 text-sm font-extrabold text-slate-800">Add pay-as-you-go credits</div>
                    <div className="grid grid-cols-3 gap-2">
                      {['25', '50', '100'].map((amount) => <button key={amount} type="button" onClick={() => setStripeAmount(amount)} className={`rounded-xl border px-3 py-3 text-sm font-extrabold ${stripeAmount === amount ? 'border-pink-500 bg-pink-50 text-pink-700' : 'border-slate-200 text-slate-600 hover:border-pink-300'}`}>${amount}</button>)}
                    </div>
                  </div>
                  <button type="button" onClick={() => createStripeCheckout()} disabled={stripeLoading} data-testid="conversion-pay" className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-pink-500 to-violet-600 px-5 py-3.5 font-extrabold text-white shadow-lg shadow-pink-500/20 disabled:opacity-50">
                    {stripeLoading ? <RefreshCw className="animate-spin" size={18} /> : <CreditCard size={18} />} Pay ${stripeAmount}
                  </button>
                  <div className="border-t border-slate-100 pt-5">
                    <div className="mb-2 text-sm font-extrabold text-slate-800">Or subscribe for unlimited images</div>
                    <p className="mb-3 text-xs font-medium text-slate-500">Includes $10/month in rollover credits for video and other metered models.</p>
                    <div className="grid grid-cols-2 gap-2">
                      <button type="button" onClick={() => createSubscriptionCheckout('monthly')} disabled={stripeLoading} className="rounded-xl border border-pink-200 bg-pink-50 px-3 py-3 text-sm font-extrabold text-pink-700 disabled:opacity-50">$14 monthly</button>
                      <button type="button" onClick={() => createSubscriptionCheckout('annual')} disabled={stripeLoading} className="rounded-xl bg-slate-950 px-3 py-3 text-sm font-extrabold text-white disabled:opacity-50">$140 yearly · save $28</button>
                    </div>
                  </div>
                  {(balance?.credits_usd || 0) > 0 && <button type="button" onClick={() => { setShowConversionFlow(false); window.setTimeout(createStudioAsset, 0); }} className="w-full rounded-xl border border-slate-200 px-5 py-3 text-sm font-extrabold text-slate-700 hover:bg-slate-50">I already have credits — create now</button>}
                </div>
              )}
              {(authStatus || stripeStatus) && <div className="mt-4 rounded-xl bg-slate-50 px-4 py-3 text-sm font-bold text-slate-600" role="status">{stripeStatus || authStatus}</div>}
            </div>
          </div>
        </div>
      )}

      {/* Hero Section */}
      <main className="relative z-10 mx-auto max-w-[1480px] px-4 pb-16 pt-4 sm:px-8 sm:pt-8 lg:pt-12">
        <div className="grid items-start gap-10 xl:grid-cols-[minmax(0,1.02fr)_minmax(460px,.98fr)] xl:gap-14">
          <div>
            <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-pink-200 bg-white px-3 py-1.5 text-[10px] font-extrabold uppercase tracking-[0.13em] text-pink-600 sm:mb-5 sm:text-xs sm:tracking-[0.14em]">
              <Sparkles size={14} /> Image + video, one simple studio
            </div>
            <h1 className="max-w-4xl font-fredoka text-[clamp(2.6rem,6vw,6.2rem)] font-bold leading-[.92] tracking-[-0.045em] text-slate-950">
              One prompt.<br />A whole world in <span className="bg-gradient-to-r from-pink-500 to-violet-600 bg-clip-text text-transparent">motion.</span>
            </h1>
            <p className="mt-4 max-w-2xl text-base font-medium leading-relaxed text-slate-600 sm:mt-6 sm:text-xl">
              Images and video from a single prompt — and the same models behind one fast API.
            </p>
            <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-2 text-sm font-extrabold">
              <Link href="/docs" className="inline-flex items-center gap-1.5 text-blue-600 hover:text-blue-700">API docs <ArrowRight size={15} /></Link>
              <Link href="/gallery" className="inline-flex items-center gap-1.5 text-pink-600 hover:text-pink-700">Gallery <ArrowRight size={15} /></Link>
              <Link href="/evals" className="inline-flex items-center gap-1.5 text-violet-600 hover:text-violet-700">Benchmarks <ArrowRight size={15} /></Link>
              <Link href="/playground" className="inline-flex items-center gap-1.5 text-slate-600 hover:text-slate-900">Playground <ArrowRight size={15} /></Link>
            </div>

            <section id="create" className="mt-6 overflow-hidden rounded-[26px] border border-slate-200 bg-white shadow-[0_22px_70px_rgba(15,23,42,.08)] sm:mt-8">
              <div className="flex border-b border-slate-200 p-2" role="tablist" aria-label="Creation mode">
                {(['image', 'video'] as const).map((mode) => (
                  <button
                    key={mode}
                    type="button"
                    role="tab"
                    aria-selected={creatorMode === mode}
                    onClick={() => setCreatorMode(mode)}
                    className={`inline-flex flex-1 items-center justify-center gap-2 rounded-2xl px-4 py-3 text-sm font-extrabold capitalize transition-colors ${creatorMode === mode ? 'bg-pink-50 text-pink-600 ring-1 ring-pink-200' : 'text-slate-500 hover:bg-slate-50 hover:text-slate-800'}`}
                  >
                    {mode === 'image' ? <ImageIcon size={18} /> : <Video size={18} />}
                    {mode}
                  </button>
                ))}
              </div>

              <div className="p-4 sm:p-5">
                <div className={`grid gap-3 ${creatorMode === 'video' ? 'sm:grid-cols-[minmax(0,1fr)_170px]' : ''}`}>
                  <label className="block">
                    <span className="sr-only">Creation prompt</span>
                    <textarea
                      value={creatorPrompt}
                      onChange={(event) => setCreatorPrompt(event.target.value)}
                      rows={4}
                      maxLength={1200}
                      className="h-full min-h-24 w-full resize-none rounded-2xl border border-slate-200 bg-slate-50/70 px-4 py-3 text-base font-medium leading-relaxed text-slate-900 outline-none transition focus:border-pink-400 focus:bg-white focus:ring-4 focus:ring-pink-100 sm:min-h-32"
                      placeholder={creatorMode === 'image' ? 'Describe the image you want to create…' : 'Describe how the camera or subject should move…'}
                    />
                  </label>
                  {creatorMode === 'video' && (
                    <label className="relative flex min-h-32 cursor-pointer flex-col items-center justify-center overflow-hidden rounded-2xl border border-dashed border-slate-300 bg-slate-50 px-3 text-center transition hover:border-pink-400 hover:bg-pink-50">
                      {creatorReferencePreview ? (
                        <img src={creatorReferencePreview} alt="Video reference preview" className="absolute inset-0 h-full w-full object-contain bg-slate-950" />
                      ) : (
                        <>
                          <Upload className="mb-2 text-slate-400" size={22} />
                          <span className="text-sm font-extrabold text-slate-700">Add still image</span>
                          <span className="mt-1 text-xs text-slate-400">PNG, JPG or WebP</span>
                        </>
                      )}
                      <input type="file" accept="image/png,image/jpeg,image/webp" className="sr-only" onChange={(event) => setCreatorReference(event.target.files?.[0] || null)} />
                    </label>
                  )}
                </div>

                <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-[1fr_1fr_auto]">
                  {creatorMode === 'video' ? (
                    <label className="relative">
                      <span className="mb-1.5 block text-[11px] font-extrabold uppercase tracking-wider text-slate-500">Model</span>
                      <select value={creatorModel} onChange={(event) => setCreatorModel(event.target.value)} className="w-full appearance-none rounded-xl border border-slate-200 bg-white px-3 py-2.5 pr-9 text-sm font-bold text-slate-800 outline-none focus:border-pink-400">
                        <option value="auto-video">Auto · best match</option>
                        <option value="ltx-video">LTX · fast</option>
                        <option value="ltx-2">LTX 2 · balanced</option>
                        <option value="ltx-2.3-image-to-video">LTX 2.3 · premium I2V</option>
                      </select>
                      <ChevronDown className="pointer-events-none absolute bottom-3 right-3 text-slate-400" size={16} />
                    </label>
                  ) : (
                    <div>
                      <span className="mb-1.5 block text-[11px] font-extrabold uppercase tracking-wider text-slate-500">Model</span>
                      <div className="rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm font-bold text-slate-800">Z-Image Turbo</div>
                    </div>
                  )}
                  <label>
                    <span className="mb-1.5 block text-[11px] font-extrabold uppercase tracking-wider text-slate-500">Aspect ratio</span>
                    <select value={creatorAspect} onChange={(event) => setCreatorAspect(event.target.value)} className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm font-bold text-slate-800 outline-none focus:border-pink-400">
                      <option value="16:9">16:9 · Widescreen</option>
                      <option value="1:1">1:1 · Square</option>
                      <option value="9:16">9:16 · Portrait</option>
                      <option value="4:3">4:3 · Classic</option>
                    </select>
                  </label>
                  <div className="col-span-2 flex items-end sm:col-span-1">
                    <button type="button" onClick={createStudioAsset} disabled={creatorLoading} className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-pink-500 to-rose-500 px-6 py-3 text-sm font-extrabold text-white shadow-lg shadow-pink-500/20 transition hover:brightness-105 disabled:cursor-wait disabled:opacity-60 sm:w-auto">
                      {creatorLoading ? <RefreshCw className="animate-spin" size={18} /> : <Sparkles size={18} />}
                      Create now
                    </button>
                  </div>
                </div>

                <div className="mt-4 flex flex-col gap-3 border-t border-slate-100 pt-4 text-xs font-bold text-slate-500 sm:flex-row sm:items-center sm:justify-between">
                  <span>{creatorMode === 'image' ? '$0.04 / image' : creatorModel === 'ltx-video' ? '$0.08 / video' : creatorModel === 'ltx-2' ? '$0.12 / video' : creatorModel === 'ltx-2.3-image-to-video' ? '$1.85 / video' : '$0.15 / video'}</span>
                  <span className="inline-flex items-center gap-1.5"><LockKeyhole size={14} className="text-emerald-600" /> Pay as you go · <Link href="/docs" className="text-blue-600 hover:text-blue-700">same models via API</Link></span>
                </div>
                {creatorStatus && <div className="mt-3 rounded-xl bg-slate-50 px-4 py-3 text-sm font-bold text-slate-600" role="status">{creatorStatus}</div>}
                {creatorResult && (
                  <div className="mt-4 overflow-hidden rounded-2xl border border-slate-200 bg-slate-950">
                    {creatorResult.type === 'video' ? (
                      <video src={creatorResult.url} controls playsInline className="max-h-[520px] w-full object-contain" />
                    ) : (
                      <img src={creatorResult.url} alt="Your generated result" className="max-h-[520px] w-full object-contain" />
                    )}
                  </div>
                )}
              </div>
            </section>
          </div>

          <div className="relative mx-auto w-full max-w-2xl xl:pt-16">
            <div className="ml-auto w-[82%] overflow-hidden rounded-[26px] border border-slate-200 bg-slate-950 shadow-[0_24px_80px_rgba(15,23,42,.16)]">
              <div className="relative aspect-[4/3]">
                <Image src={`${IMG_BASE}/hero.webp`} alt="AI-generated pink-haired character in a neon city" fill priority sizes="(min-width: 1280px) 38vw, 80vw" className="object-cover object-top" />
              </div>
            </div>
            <div className="relative -mt-12 mr-auto w-[90%] overflow-hidden rounded-[26px] border-4 border-white bg-slate-950 shadow-[0_24px_80px_rgba(15,23,42,.22)] sm:-mt-20">
              <div className="relative aspect-video overflow-hidden">
                {/* Real LTX 2.3 image-to-video output, conditioned on the Z-Image still above. */}
                <video
                  className="h-full w-full object-cover"
                  poster={`${VIDEO_BASE}/hero-reel-poster.webp`}
                  autoPlay
                  muted
                  loop
                  playsInline
                  preload="metadata"
                  aria-label="LTX 2.3 animation of the pink-haired character shown above"
                >
                  <source src={`${VIDEO_BASE}/hero-reel-av1.mp4`} type="video/mp4; codecs=av01.0.05M.08" />
                  <source src={`${VIDEO_BASE}/hero-reel.mp4`} type="video/mp4" />
                </video>
                <div className="pointer-events-none absolute inset-x-4 bottom-4 flex items-center justify-end">
                  <span className="rounded-full bg-slate-950/70 px-2.5 py-1 text-[10px] font-extrabold uppercase tracking-widest text-white">AV1</span>
                </div>
              </div>
            </div>
            <div className="absolute right-2 top-1/2 hidden rounded-2xl border border-violet-200 bg-white p-3 shadow-xl sm:block">
              <div className="flex items-center gap-2 text-sm font-extrabold text-slate-800"><Video size={17} className="text-violet-600" /> Made on CuteDSL</div>
              <div className="mt-1 text-xs font-bold text-slate-400">Z-Image → LTX 2.3 · AV1</div>
            </div>
          </div>
        </div>

        <div className="mt-12 grid overflow-hidden rounded-[24px] border border-slate-200 bg-white shadow-sm sm:grid-cols-2 lg:grid-cols-6">
          {[
            ['1', 'Describe it', 'Prompt or drop a still'],
            ['2', 'Sign up', 'Takes seconds'],
            ['3', 'Create', 'Pay only for what you make'],
          ].map(([number, title, copy]) => (
            <div key={number} className="flex items-center gap-3 border-b border-slate-100 p-4 sm:border-r lg:col-span-1 lg:border-b-0">
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-pink-500 text-sm font-black text-white">{number}</span>
              <div><div className="text-sm font-extrabold text-slate-900">{title}</div><div className="text-xs font-bold text-slate-400">{copy}</div></div>
            </div>
          ))}
          <div className="grid grid-cols-3 divide-x divide-slate-100 lg:col-span-3">
            {([[Sparkles, '8+ models', '#models'], [Code, 'API included', '/docs'], [ShieldCheck, 'Commercial use', '/docs']] as const).map(([Icon, label, href]) => {
              const ProofIcon = Icon as typeof Sparkles;
              return (
                <Link key={label} href={href} className="flex flex-col items-center justify-center gap-1 p-4 text-center text-xs font-extrabold text-slate-700 transition-colors hover:bg-slate-50 hover:text-violet-700">
                  <ProofIcon size={20} className="text-violet-600" />{label}
                </Link>
              );
            })}
          </div>
        </div>
      </main>

      {/* E2E Test Panel (shown with ?test=true) */}
      {testMode && (
        <div className="fixed top-0 right-0 z-50 bg-slate-900 text-white p-4 rounded-bl-2xl shadow-2xl max-w-sm max-h-96 overflow-y-auto">
          <div className="font-bold mb-2 text-green-400">E2E API Tests</div>
          {testResults.length === 0 && <div className="text-slate-400 text-sm">Running...</div>}
          {testResults.map((r, i) => (
            <div key={i} className="flex justify-between text-xs py-1 border-b border-slate-700">
              <span className="font-mono">{r.route}</span>
              <span className={r.status.includes('FAIL') || r.status === 'ERR' ? 'text-red-400' : 'text-green-400'}>
                {r.status} ({r.ms}ms)
              </span>
            </div>
          ))}
          {testResults.length > 0 && (
            <div className="mt-2 text-xs text-slate-400">
              {testResults.filter(r => r.status.includes('OK')).length}/{testResults.length} passed
            </div>
          )}
        </div>
      )}

      {/* Models Section */}
      <section id="models" className="py-24 relative z-10">
        <div className="absolute inset-0 bg-white/55 -z-10"></div>
        <div className="max-w-7xl mx-auto px-6">
          <div className="text-center mb-16 relative">
            <h2 className="font-fredoka text-4xl lg:text-5xl font-bold text-slate-800 mb-4">Our Models</h2>
            <p className="text-lg text-slate-700 max-w-2xl mx-auto font-medium">Fast, beautiful models &mdash; each one live in the <Link href="/docs" className="text-blue-600 font-bold hover:text-blue-700">API docs</Link>.</p>
            <Link href="/tools" className="mt-5 inline-flex items-center gap-2 rounded-full border border-purple-200 bg-white/80 px-5 py-2.5 text-sm font-extrabold text-purple-700 shadow-sm transition hover:bg-purple-50">
              Explore music, H3 video &amp; animation tools <ArrowRight size={16} />
            </Link>
          </div>

          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6">
            <Link href="/docs/zimage">
            <div className="glass-card card-hover p-6 rounded-3xl relative overflow-hidden group bg-white/70 cursor-pointer">
              <div className="bg-pink-100 w-14 h-14 rounded-2xl flex items-center justify-center text-pink-500 mb-4 shadow-inner">
                <ImageIcon size={28} />
              </div>
              <h3 className="font-fredoka text-2xl font-bold text-slate-800 mb-2 group-hover:text-pink-600 transition-colors">zimage</h3>
              <p className="text-slate-600 mb-4 text-sm">
                Gorgeous 1024px images in about a second. Our fastest text-to-image model.
              </p>
              <div className="mt-auto">
                <div className="flex items-center gap-2 text-pink-500 font-bold text-sm">
                  <Zap size={16} /> {formatUsd(getServiceUsd('zimage'))} <span className="text-slate-400 font-medium">/ gen</span>
                </div>
                {getServicePrice('zimage') > 0 && (
                  <div className="text-xs text-slate-400 mt-1">&asymp; {formatCute(getServicePrice('zimage'))} $CUTEDSL</div>
                )}
              </div>
            </div>
            </Link>

            <Link href="/docs/chronos2">
            <div className="glass-card card-hover p-6 rounded-3xl relative overflow-hidden group bg-white/70 cursor-pointer">
              <div className="bg-cyan-100 w-14 h-14 rounded-2xl flex items-center justify-center text-cyan-500 mb-4 shadow-inner">
                <LineChart size={28} />
              </div>
              <h3 className="font-fredoka text-2xl font-bold text-slate-800 mb-2 group-hover:text-cyan-600 transition-colors">chronos2</h3>
              <p className="text-slate-600 mb-4 text-sm">
                Forecast any time series in milliseconds, with confidence bands built in.
              </p>
              <div className="mt-auto">
                <div className="flex items-center gap-2 text-cyan-500 font-bold text-sm">
                  <Zap size={16} /> {formatUsd(getServiceUsd('chronos2'))} <span className="text-slate-400 font-medium">/ forecast</span>
                </div>
                {getServicePrice('chronos2') > 0 && (
                  <div className="text-xs text-slate-400 mt-1">&asymp; {formatCute(getServicePrice('chronos2'))} $CUTEDSL</div>
                )}
              </div>
            </div>
            </Link>

            <Link href="/docs/tts">
            <div className="glass-card card-hover p-6 rounded-3xl relative overflow-hidden group bg-white/70 cursor-pointer">
              <div className="bg-purple-100 w-14 h-14 rounded-2xl flex items-center justify-center text-purple-500 mb-4 shadow-inner">
                <Volume2 size={28} />
              </div>
              <h3 className="font-fredoka text-2xl font-bold text-slate-800 mb-2 group-hover:text-purple-600 transition-colors">Kokoro TTS</h3>
              <p className="text-slate-600 mb-4 text-sm">
                Natural speech in 20+ voices and languages.
              </p>
              <div className="mt-auto">
                <div className="flex items-center gap-2 text-purple-500 font-bold text-sm">
                  <Zap size={16} /> {formatUsd(getServiceUsd('tts'))} <span className="text-slate-400 font-medium">/ 100 chars</span>
                </div>
                {getServicePrice('tts') > 0 && (
                  <div className="text-xs text-slate-400 mt-1">&asymp; {formatCute(getServicePrice('tts'))} $CUTEDSL</div>
                )}
              </div>
            </div>
            </Link>

            <Link href="/docs/stt">
            <div className="glass-card card-hover p-6 rounded-3xl relative overflow-hidden group bg-white/70 cursor-pointer">
              <div className="bg-blue-100 w-14 h-14 rounded-2xl flex items-center justify-center text-blue-500 mb-4 shadow-inner">
                <Mic size={28} />
              </div>
              <h3 className="font-fredoka text-2xl font-bold text-slate-800 mb-2 group-hover:text-blue-600 transition-colors">Speech-to-Text</h3>
              <p className="text-slate-600 mb-4 text-sm">
                Accurate transcription for any audio you throw at it.
              </p>
              <div className="mt-auto">
                <div className="flex items-center gap-2 text-blue-500 font-bold text-sm">
                  <Zap size={16} /> {formatUsd(getServiceUsd('stt'))} <span className="text-slate-400 font-medium">/ minute</span>
                </div>
                {getServicePrice('stt') > 0 && (
                  <div className="text-xs text-slate-400 mt-1">&asymp; {formatCute(getServicePrice('stt'))} $CUTEDSL</div>
                )}
              </div>
            </div>
            </Link>

            <Link href="/docs/gemma4">
            <div className="glass-card card-hover p-6 rounded-3xl relative overflow-hidden group bg-white/70 cursor-pointer">
              <div className="bg-emerald-100 w-14 h-14 rounded-2xl flex items-center justify-center text-emerald-500 mb-4 shadow-inner">
                <Cpu size={28} />
              </div>
              <h3 className="font-fredoka text-2xl font-bold text-slate-800 mb-2 group-hover:text-emerald-600 transition-colors">Gemma4 Chat</h3>
              <p className="text-slate-600 mb-4 text-sm">
                Chat and vision in one model, on an OpenAI-compatible API.
              </p>
              <div className="mt-auto">
                <div className="flex items-center gap-2 text-emerald-500 font-bold text-sm">
                  <Zap size={16} /> {formatUsd(getServiceUsd('gemma4'))} <span className="text-slate-400 font-medium">/ request</span>
                </div>
                {getServicePrice('gemma4') > 0 && (
                  <div className="text-xs text-slate-400 mt-1">&asymp; {formatCute(getServicePrice('gemma4'))} $CUTEDSL</div>
                )}
              </div>
            </div>
            </Link>

            <Link href="/docs/caption">
            <div className="glass-card card-hover p-6 rounded-3xl relative overflow-hidden group bg-white/70 cursor-pointer">
              <div className="bg-orange-100 w-14 h-14 rounded-2xl flex items-center justify-center text-orange-500 mb-4 shadow-inner">
                <Search size={28} />
              </div>
              <h3 className="font-fredoka text-2xl font-bold text-slate-800 mb-2 group-hover:text-orange-600 transition-colors">Image Caption</h3>
              <p className="text-slate-600 mb-4 text-sm">
                Describe any image &mdash; for search, accessibility, or your own pipelines.
              </p>
              <div className="mt-auto">
                <div className="flex items-center gap-2 text-orange-500 font-bold text-sm">
                  <Zap size={16} /> {formatUsd(getServiceUsd('caption'))} <span className="text-slate-400 font-medium">/ image</span>
                </div>
                {getServicePrice('caption') > 0 && (
                  <div className="text-xs text-slate-400 mt-1">&asymp; {formatCute(getServicePrice('caption'))} $CUTEDSL</div>
                )}
              </div>
            </div>
            </Link>

            <Link href="/docs/ltx_video">
            <div className="glass-card card-hover p-6 rounded-3xl relative overflow-hidden group bg-white/70 cursor-pointer">
              <div className="bg-red-100 w-14 h-14 rounded-2xl flex items-center justify-center text-red-500 mb-4 shadow-inner">
                <Gamepad2 size={28} />
              </div>
              <h3 className="font-fredoka text-2xl font-bold text-slate-800 mb-2 group-hover:text-red-600 transition-colors">LTX 2.3 Video</h3>
              <p className="text-slate-600 mb-4 text-sm">
                Six seconds of 1080p video from a single prompt.
              </p>
              <div className="mt-auto">
                <div className="flex items-center gap-2 text-red-500 font-bold text-sm">
                  <Zap size={16} /> {formatUsd(getServiceUsd('ltx_video'))} <span className="text-slate-400 font-medium">/ video</span>
                </div>
                {getServicePrice('ltx_video') > 0 && (
                  <div className="text-xs text-slate-400 mt-1">&asymp; {formatCute(getServicePrice('ltx_video'))} $CUTEDSL</div>
                )}
              </div>
            </div>
            </Link>

            <Link href="/docs/h3_video">
            <div className="glass-card card-hover p-6 rounded-3xl relative overflow-hidden group bg-white/70 cursor-pointer">
              <div className="bg-teal-100 w-14 h-14 rounded-2xl flex items-center justify-center text-teal-600 mb-4 shadow-inner">
                <Video size={28} />
              </div>
              <h3 className="font-fredoka text-2xl font-bold text-slate-800 mb-2 group-hover:text-teal-700 transition-colors">MiniMax H3 Video</h3>
              <p className="text-slate-600 mb-4 text-sm">
                Text or first-frame video with native audio, seamless loops, and GPU AV1 through app.nz.
              </p>
              <div className="mt-auto">
                <div className="flex items-center gap-2 text-teal-600 font-bold text-sm">
                  <Zap size={16} /> {formatUsd(getServiceUsd('h3_video'))} <span className="text-slate-400 font-medium">/ GPU-hour</span>
                </div>
                {getServicePrice('h3_video') > 0 && (
                  <div className="text-xs text-slate-400 mt-1">&asymp; {formatCute(getServicePrice('h3_video'))} $CUTEDSL / GPU-hour · metered per execution</div>
                )}
              </div>
            </div>
            </Link>

            <Link href="/docs/flux_image">
            <div className="glass-card card-hover p-6 rounded-3xl relative overflow-hidden group bg-white/70 cursor-pointer">
              <div className="bg-indigo-100 w-14 h-14 rounded-2xl flex items-center justify-center text-indigo-500 mb-4 shadow-inner">
                <Globe size={28} />
              </div>
              <h3 className="font-fredoka text-2xl font-bold text-slate-800 mb-2 group-hover:text-indigo-600 transition-colors">Flux Image</h3>
              <p className="text-slate-600 mb-4 text-sm">
                Quick 1024px drafts when you want ideas fast.
              </p>
              <div className="mt-auto">
                <div className="flex items-center gap-2 text-indigo-500 font-bold text-sm">
                  <Zap size={16} /> {formatUsd(getServiceUsd('flux_image'))} <span className="text-slate-400 font-medium">/ image</span>
                </div>
                {getServicePrice('flux_image') > 0 && (
                  <div className="text-xs text-slate-400 mt-1">&asymp; {formatCute(getServicePrice('flux_image'))} $CUTEDSL</div>
                )}
              </div>
            </div>
            </Link>
          </div>
        </div>
      </section>

      {/* Try It - Image Gen Demo */}
      {walletAddress && apiKey && (
        <section className="py-16 relative z-10">
          <div className="max-w-4xl mx-auto px-6">
            <div className="bg-white/90 rounded-3xl p-8 border border-pink-200 shadow-lg">
              <h2 className="font-fredoka text-3xl font-bold text-slate-800 mb-2">Try It</h2>
              <p className="text-slate-500 mb-6 text-sm">Generate an image with your key &mdash; the same call your app would make. <Link href="/docs/zimage" className="text-blue-600 font-bold hover:text-blue-700">See the docs</Link>.</p>
              <div className="flex gap-3 mb-4">
                <input
                  type="text"
                  value={demoPrompt}
                  onChange={e => setDemoPrompt(e.target.value)}
                  className="flex-1 px-4 py-3 rounded-xl border border-slate-200 focus:border-pink-400 focus:ring-2 focus:ring-pink-200 outline-none"
                  placeholder="a cute fairy in a forest..."
                />
                <button
                  onClick={tryImageGen}
                  disabled={demoLoading}
                  className="bg-gradient-to-r from-pink-400 to-purple-400 text-white font-bold px-6 py-3 rounded-xl hover:scale-105 transition-transform disabled:opacity-50 flex items-center gap-2"
                >
                  {demoLoading ? <RefreshCw size={18} className="animate-spin" /> : <ImageIcon size={18} />}
                  Generate
                </button>
              </div>
              <CodeBlock language="bash" className="text-xs bg-slate-950 p-3 rounded-lg mb-4 shadow-none" code={`curl -X POST ${clientOrigin}/api/service \\
  -H "Authorization: Bearer ${apiKey}" \\
  -H "Content-Type: application/json" \\
  -d '{"prompt":"${demoPrompt}","width":512,"height":512}'`} />
              {demoResult && (
                <div className="mt-4">
                  <img src={demoResult} alt="Generated" className="rounded-2xl shadow-lg max-w-full mx-auto" style={{maxHeight: 512}} />
                </div>
              )}
            </div>
          </div>
        </section>
      )}

      {/* LoRA Training & Inference */}
      <section id="training" className="py-24 relative z-10">
        <div className="max-w-7xl mx-auto px-6">
          <div className="glass-card rounded-3xl p-10 lg:p-16 flex flex-col lg:flex-row items-center gap-12 bg-gradient-to-r from-purple-100/90 to-pink-100/90">
            <div className="flex-1 relative">
              <div className="bg-purple-200 w-16 h-16 rounded-2xl flex items-center justify-center text-purple-600 mb-6 shadow-inner">
                <Wand2 size={32} />
              </div>
              <h2 className="font-fredoka text-4xl lg:text-5xl font-bold text-slate-800 mb-6">Train your own style</h2>
              <p className="text-lg text-slate-700 mb-8 font-medium">
                Upload a handful of images and get a custom model that draws like you &mdash; ready to call from the API.
              </p>
              <div className="flex flex-wrap items-center gap-4">
                <Link href="/lora-trainer" className="bg-purple-500 text-white font-bold px-8 py-4 rounded-full shadow-lg hover:bg-purple-600 transition-colors">
                  Start training
                </Link>
                <Link href="/docs/lora_training" className="font-bold text-purple-700 hover:text-purple-800 inline-flex items-center gap-2">
                  Training API docs <ArrowRight size={16} />
                </Link>
              </div>
            </div>
            <div className="flex-1 relative w-full aspect-video rounded-2xl overflow-hidden shadow-2xl border-4 border-white/50">
              <Image
                src={`${IMG_BASE}/training.webp`}
                alt="LoRA fine-tuning for zimage and chronos2 models"
                fill
                loading="lazy"
                className="object-cover"
              />
            </div>
          </div>
        </div>
      </section>

      {/* API Usage & Cloud Credits */}
      <section id="api" className="py-24 relative z-10">
        <div className="absolute inset-0 bg-blue-50/70 -z-10"></div>
        <div className="max-w-7xl mx-auto px-6">
          <div className="text-center mb-16">
            <h2 className="font-fredoka text-4xl lg:text-5xl font-bold text-slate-800 mb-4">Developer API</h2>
            <p className="text-lg text-slate-700 max-w-2xl mx-auto font-medium">Ship the same models straight into your product.</p>
          </div>

          <div className="grid md:grid-cols-2 gap-8">
            <div className="glass-card p-10 rounded-3xl bg-white/80">
              <div className="flex items-center gap-4 mb-6">
                <div className="bg-blue-100 p-4 rounded-2xl text-blue-600"><BookOpen size={32} /></div>
                <h3 className="font-fredoka text-3xl font-bold text-slate-800">API Usage Docs</h3>
              </div>
              <p className="text-slate-600 mb-8 text-lg">
                Every model on this page, behind one endpoint and one key.
              </p>
              <div className="flex flex-wrap gap-x-6 gap-y-2 font-bold">
                <Link href="/docs" className="inline-flex items-center gap-2 text-blue-600 hover:text-blue-700">API docs <ArrowRight size={16} /></Link>
                <Link href="/playground" className="inline-flex items-center gap-2 text-violet-600 hover:text-violet-700">Playground <ArrowRight size={16} /></Link>
                <Link href="/evals" className="inline-flex items-center gap-2 text-pink-600 hover:text-pink-700">Benchmarks <ArrowRight size={16} /></Link>
              </div>
            </div>

            <div className="glass-card p-10 rounded-3xl bg-white/80" id="credits">
              <div className="flex items-center gap-4 mb-6">
                <div className="bg-yellow-100 p-4 rounded-2xl text-yellow-600"><Cloud size={32} /></div>
                <h3 className="font-fredoka text-3xl font-bold text-slate-800">Cloud Credits</h3>
              </div>

              {signedIn ? (
                <div className="space-y-6">
                  {/* Balance */}
                  <div className="bg-gradient-to-r from-yellow-50 to-pink-50 p-6 rounded-2xl border border-yellow-200">
                    <div className="text-sm text-slate-500 mb-1">Your Balance</div>
                    <div className="text-3xl font-fredoka font-bold text-slate-800">
                      {balance ? formatCute(balance.credits) : '...'} <span className="text-pink-500">$CUTEDSL</span>
                    </div>
                    {balance && cutePrice > 0 && (
                      <div className="text-sm text-slate-400 mt-1">&asymp; ${(balance.credits * cutePrice).toFixed(2)} USD</div>
                    )}
                  </div>

                  {/* Email/password billing login */}
                  {(!email || !balance?.has_password) ? (
                    <div className="bg-gradient-to-r from-indigo-50 to-purple-50 p-5 rounded-2xl border border-indigo-200">
                      <div className="text-sm font-bold text-slate-700 mb-1">Set up card checkout</div>
                      <div className="text-xs text-slate-500 mb-3">Credits are tied to this email.</div>
                      <div className="grid gap-2 sm:grid-cols-[1fr_1fr_auto]">
                        <input
                          type="email"
                          value={emailInput}
                          onChange={(e) => setEmailInput(e.target.value)}
                          onKeyDown={(e) => e.key === 'Enter' && saveEmail()}
                          className="flex-1 px-4 py-2.5 rounded-xl border border-slate-200 focus:border-indigo-400 focus:ring-2 focus:ring-indigo-200 outline-none text-sm"
                          placeholder="your@email.com"
                        />
                        <input
                          type="password"
                          value={passwordInput}
                          onChange={(e) => setPasswordInput(e.target.value)}
                          onKeyDown={(e) => e.key === 'Enter' && saveEmail()}
                          className="flex-1 px-4 py-2.5 rounded-xl border border-slate-200 focus:border-indigo-400 focus:ring-2 focus:ring-indigo-200 outline-none text-sm"
                          placeholder="8+ character password"
                        />
                        <button
                          onClick={saveEmail}
                          disabled={emailSaving || !isValidEmail(emailInput) || passwordInput.length < 8}
                          className="bg-gradient-to-r from-indigo-400 to-purple-400 text-white font-bold px-5 py-2.5 rounded-xl hover:scale-105 transition-transform disabled:opacity-50 text-sm"
                        >
                          {emailSaving ? <RefreshCw size={16} className="animate-spin" /> : emailSaved ? <Check size={16} /> : 'Save'}
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div className="flex items-center gap-2 text-sm text-slate-500 bg-indigo-50/50 px-4 py-2 rounded-xl">
                      <Check size={14} className="text-green-500" />
                      Card login ready for {email}
                    </div>
                  )}
                  {authStatus && (
                    <div className={`rounded-lg px-3 py-2 text-sm font-medium ${authStatus.toLowerCase().includes('failed') || authStatus.toLowerCase().includes('required') || authStatus.toLowerCase().includes('use') ? 'bg-red-50 text-red-600' : 'bg-green-50 text-green-600'}`}>
                      {authStatus}
                    </div>
                  )}

                  {/* Buy / Deposit Tabs */}
                  <div>
                    <div className="flex gap-1 mb-3 bg-slate-100 p-1 rounded-xl">
                      <button
                        onClick={() => setBuyTab('card')}
                        className={`flex-1 py-2 px-3 rounded-lg text-sm font-bold transition-all ${buyTab === 'card' ? 'bg-gradient-to-r from-pink-400 to-purple-400 text-white shadow-sm' : 'text-slate-500 hover:text-slate-700'}`}
                      >
                        Card
                      </button>
                      <button
                        onClick={() => setBuyTab('buy')}
                        className={`flex-1 py-2 px-3 rounded-lg text-sm font-bold transition-all ${buyTab === 'buy' ? 'bg-gradient-to-r from-pink-400 to-purple-400 text-white shadow-sm' : 'text-slate-500 hover:text-slate-700'}`}
                      >
                        Buy $CUTEDSL
                      </button>
                      <button
                        onClick={() => setBuyTab('deposit')}
                        className={`flex-1 py-2 px-3 rounded-lg text-sm font-bold transition-all ${buyTab === 'deposit' ? 'bg-gradient-to-r from-pink-400 to-purple-400 text-white shadow-sm' : 'text-slate-500 hover:text-slate-700'}`}
                      >
                        Deposit
                      </button>
                    </div>

                    {buyTab === 'card' ? (
                      <div className="space-y-4">
                        {!cardCheckoutReady ? (
                          <div className="rounded-2xl border border-dashed border-pink-200 bg-pink-50/60 p-5">
                            <div className="mb-1 text-sm font-bold text-slate-700">Email required before checkout</div>
                            <div className="text-xs text-slate-500">Save your email and password above first.</div>
                          </div>
                        ) : (
                          <>
                            {embeddedCheckoutClientSecret ? (
                              <div className="rounded-2xl border border-slate-200 bg-white p-3 shadow-sm" data-testid="embedded-checkout-container">
                                <div className="mb-3 flex items-center justify-between gap-3 px-1">
                                  <div>
                                    <div className="text-sm font-bold text-slate-700">Secure card checkout</div>
                                    <div className="text-xs text-slate-400">Checkout for {email}</div>
                                  </div>
                                  <button
                                    type="button"
                                    onClick={() => setEmbeddedCheckoutClientSecret('')}
                                    className="rounded-lg p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
                                    aria-label="Close Stripe checkout"
                                  >
                                    <X size={16} />
                                  </button>
                                </div>
                                <div ref={embeddedCheckoutElementRef} className="min-h-[440px]" />
                              </div>
                            ) : (
                              <>
                                <div className="flex gap-2">
                                  <div className="relative flex-1">
                                    <span className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400">$</span>
                                    <input
                                      type="number"
                                      min="1"
                                      max="500"
                                      value={stripeAmount}
                                      onChange={(e) => setStripeAmount(e.target.value)}
                                      className="w-full pl-7 pr-4 py-3 rounded-xl border border-slate-200 focus:border-pink-400 focus:ring-2 focus:ring-pink-200 outline-none text-lg"
                                      placeholder="25"
                                    />
                                  </div>
                                  <button
                                    onClick={() => createStripeCheckout()}
                                    disabled={stripeLoading || !stripeAmount}
                                    data-testid="stripe-checkout-btn"
                                    className="bg-gradient-to-r from-pink-400 to-purple-400 text-white font-bold px-6 py-3 rounded-xl hover:scale-105 transition-transform disabled:opacity-50 inline-flex items-center gap-2"
                                  >
                                    {stripeLoading ? <RefreshCw size={20} className="animate-spin" /> : <CreditCard size={18} />}
                                    Pay
                                  </button>
                                </div>
                                {cutePrice > 0 && stripeAmount && (
                                  <div className="text-xs text-slate-400">
                                    Buys &asymp; {formatCute(parseFloat(stripeAmount || '0') / cutePrice)} $CUTEDSL. Stripe will save your card for optional auto top-up after checkout.
                                  </div>
                                )}
                              </>
                            )}

                            <div className="bg-white/70 rounded-2xl border border-slate-200 p-4 space-y-3">
                              <div className="flex items-center justify-between gap-3">
                                <div>
                                  <div className="text-sm font-bold text-slate-700">Auto top-up</div>
                                  <div className="text-xs text-slate-400">Charge your saved Stripe card when your balance is low.</div>
                                </div>
                                <button
                                  type="button"
                                  onClick={() => setAutotopupEnabled(!autotopupEnabled)}
                                  className={`w-12 h-7 rounded-full p-1 transition-colors ${autotopupEnabled ? 'bg-pink-500' : 'bg-slate-300'}`}
                                  aria-pressed={autotopupEnabled}
                                >
                                  <span className={`block h-5 w-5 rounded-full bg-white transition-transform ${autotopupEnabled ? 'translate-x-5' : 'translate-x-0'}`} />
                                </button>
                              </div>
                              <div className="grid grid-cols-2 gap-3">
                                <label className="text-xs font-bold text-slate-500">
                                  Threshold USD
                                  <input
                                    type="number"
                                    min="1"
                                    max="100"
                                    value={autotopupThreshold}
                                    onChange={(e) => setAutotopupThreshold(e.target.value)}
                                    className="mt-1 w-full px-3 py-2 rounded-lg border border-slate-200 focus:border-pink-400 focus:ring-2 focus:ring-pink-200 outline-none text-sm font-normal text-slate-700"
                                  />
                                </label>
                                <label className="text-xs font-bold text-slate-500">
                                  Top-up USD
                                  <input
                                    type="number"
                                    min="5"
                                    max="500"
                                    value={autotopupAmount}
                                    onChange={(e) => setAutotopupAmount(e.target.value)}
                                    className="mt-1 w-full px-3 py-2 rounded-lg border border-slate-200 focus:border-pink-400 focus:ring-2 focus:ring-pink-200 outline-none text-sm font-normal text-slate-700"
                                  />
                                </label>
                              </div>
                              <button
                                onClick={saveAutotopupSettings}
                                disabled={autotopupSaving || stripeLoading}
                                className="w-full bg-slate-800 text-white font-bold px-4 py-2.5 rounded-xl hover:bg-slate-700 transition-colors disabled:opacity-50"
                              >
                                {autotopupSaving ? 'Saving...' : 'Save auto top-up'}
                              </button>
                              {balance && !balance.has_payment_method && (
                                <div className="text-xs text-amber-600 bg-amber-50 px-3 py-2 rounded-lg">
                                  No card saved yet. Saving with auto top-up on opens a Stripe checkout that saves your card.
                                </div>
                              )}
                            </div>
                          </>
                        )}

                        {stripeStatus && (
                          <div className={`text-sm font-medium px-3 py-2 rounded-lg ${stripeStatus.includes('failed') || stripeStatus.includes('Failed') || stripeStatus.includes('cancelled') || stripeStatus.includes('before enabling') || stripeStatus.includes('Add ') ? 'bg-red-50 text-red-600' : 'bg-green-50 text-green-600'}`}>
                            {stripeStatus}
                          </div>
                        )}
                      </div>
                    ) : buyTab === 'buy' ? (
                      !hasSolanaWallet ? (
                        <div className="rounded-2xl border border-dashed border-purple-200 bg-purple-50/60 p-5 text-center">
                          <div className="mb-2 text-sm font-bold text-slate-700">Connect a Solana wallet to buy with SOL</div>
                          <p className="mb-4 text-xs text-slate-500">Your email/card account stays linked after connecting.</p>
                          <button
                            onClick={connectWallet}
                            disabled={connectingWallet}
                            className="inline-flex items-center gap-2 rounded-xl bg-slate-900 px-5 py-3 text-sm font-bold text-white disabled:opacity-50"
                          >
                            {connectingWallet ? <RefreshCw size={16} className="animate-spin" /> : <Wallet size={16} />}
                            Connect wallet
                          </button>
                        </div>
                      ) : (
                      <div className="space-y-3">
                        <div className="flex gap-2">
                          <div className="relative flex-1">
                            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 text-sm font-bold">SOL</span>
                            <input
                              type="number"
                              min="0.01"
                              step="0.01"
                              value={buySolAmount}
                              onChange={(e) => { setBuySolAmount(e.target.value); fetchSwapQuote(e.target.value); }}
                              onBlur={() => fetchSwapQuote(buySolAmount)}
                              className="w-full pl-12 pr-4 py-3 rounded-xl border border-slate-200 focus:border-pink-400 focus:ring-2 focus:ring-pink-200 outline-none text-lg"
                              placeholder="0.1"
                            />
                          </div>
                          <button
                            onClick={executeBuy}
                            disabled={buyLoading || !buySolAmount}
                            className="bg-gradient-to-r from-pink-400 to-purple-400 text-white font-bold px-6 py-3 rounded-xl hover:scale-105 transition-transform disabled:opacity-50"
                          >
                            {buyLoading ? <RefreshCw size={20} className="animate-spin" /> : 'Swap'}
                          </button>
                        </div>
                        {buyQuote && (
                          <div className="bg-pink-50 p-3 rounded-xl text-sm space-y-1">
                            <div className="flex justify-between">
                              <span className="text-slate-500">You pay</span>
                              <span className="font-bold text-slate-700">{buyQuote.sol_amount} SOL (~${buyQuote.usd_value?.toFixed(2)})</span>
                            </div>
                            <div className="flex justify-between">
                              <span className="text-slate-500">You receive</span>
                              <span className="font-bold text-pink-600">{formatCute(buyQuote.cute_amount)} $CUTEDSL</span>
                            </div>
                            {buyQuote.price_impact > 0.5 && (
                              <div className="text-xs text-orange-500">Price impact: {buyQuote.price_impact.toFixed(2)}%</div>
                            )}
                          </div>
                        )}
                        {!buyQuote && buySolAmount && parseFloat(buySolAmount) > 0 && solPrice > 0 && (
                          <div className="text-xs text-slate-400">
                            ~${(parseFloat(buySolAmount || '0') * solPrice).toFixed(2)} USD &middot; Click Swap to get live quote from bags.fm pool
                          </div>
                        )}
                        {buyStatus && (
                          <div className={`text-sm font-medium px-3 py-2 rounded-lg ${buyStatus.includes('Error') || buyStatus.includes('cancelled') ? 'bg-red-50 text-red-600' : buyStatus.includes('complete') ? 'bg-green-50 text-green-600' : 'bg-blue-50 text-blue-600'}`}>
                            {buyStatus}
                          </div>
                        )}
                        <div className="text-xs text-slate-400">
                          Swaps SOL for $CUTEDSL via bags.fm liquidity pool. Signed with your Phantom wallet.
                        </div>
                      </div>
                      )
                    ) : (
                      !hasSolanaWallet ? (
                        <div className="rounded-2xl border border-dashed border-purple-200 bg-purple-50/60 p-5 text-center">
                          <div className="mb-2 text-sm font-bold text-slate-700">Connect a Solana wallet to deposit $CUTEDSL</div>
                          <p className="mb-4 text-xs text-slate-500">Card-funded credits work with email only; token deposits need a wallet.</p>
                          <button
                            onClick={connectWallet}
                            disabled={connectingWallet}
                            className="inline-flex items-center gap-2 rounded-xl bg-slate-900 px-5 py-3 text-sm font-bold text-white disabled:opacity-50"
                          >
                            {connectingWallet ? <RefreshCw size={16} className="animate-spin" /> : <Wallet size={16} />}
                            Connect wallet
                          </button>
                        </div>
                      ) : (
                      <div className="space-y-3">
                        <div className="flex gap-2">
                          <div className="relative flex-1">
                            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400">$</span>
                            <input
                              type="number"
                              min="1"
                              value={depositAmount}
                              onChange={(e) => setDepositAmount(e.target.value)}
                              className="w-full pl-7 pr-4 py-3 rounded-xl border border-slate-200 focus:border-pink-400 focus:ring-2 focus:ring-pink-200 outline-none text-lg"
                              placeholder="10"
                            />
                          </div>
                          <button
                            onClick={createDeposit}
                            disabled={depositLoading}
                            className="bg-gradient-to-r from-pink-400 to-purple-400 text-white font-bold px-6 py-3 rounded-xl hover:scale-105 transition-transform disabled:opacity-50"
                          >
                            {depositLoading ? <RefreshCw size={20} className="animate-spin" /> : 'Deposit'}
                          </button>
                        </div>
                        {cutePrice > 0 && depositAmount && (
                          <div className="text-xs text-slate-400">
                            &asymp; {formatCute(parseFloat(depositAmount || '0') / cutePrice)} $CUTEDSL at current price (${cutePrice.toFixed(8)}/CUTEDSL)
                          </div>
                        )}
                      </div>
                      )
                    )}
                  </div>

                  {/* Deposit result */}
                  {depositResult && (
                    <div className="bg-white p-6 rounded-2xl border-2 border-pink-200 space-y-3">
                      <div className="font-bold text-slate-700">Send {depositResult.amount_ui} to:</div>
                      <div className="flex items-center gap-2">
                        <code className="bg-slate-100 px-3 py-2 rounded-lg text-sm flex-1 break-all">{depositResult.deposit_address}</code>
                        <button onClick={() => copyToClipboard(depositResult.deposit_address)} className="p-2 hover:bg-slate-100 rounded-lg">
                          {copied ? <Check size={18} className="text-green-500" /> : <Copy size={18} className="text-slate-400" />}
                        </button>
                      </div>
                      {depositResult.solana_pay_url && (
                        <a href={depositResult.solana_pay_url} className="inline-flex items-center gap-2 text-purple-600 font-bold text-sm hover:text-purple-700">
                          Open in Wallet <ArrowRight size={14} />
                        </a>
                      )}
                      <div className="text-xs text-slate-400">Waiting for payment... This will update automatically.</div>
                    </div>
                  )}

                  {/* Recent transactions */}
                  {billingHistory.length > 0 && (
                    <div>
                      <div className="text-sm font-bold text-slate-600 mb-2">Recent Activity</div>
                      <div className="space-y-1 max-h-48 overflow-y-auto">
                        {billingHistory.slice(0, 10).map(event => (
                          <div key={event.id} className="flex justify-between items-center text-sm py-2 px-3 bg-white/60 rounded-lg">
                            <span className="text-slate-600">{event.description}</span>
                            <span className={`font-bold ${event.amount >= 0 ? 'text-green-600' : 'text-red-500'}`}>
                              {event.amount >= 0 ? '+' : ''}{formatCute(Math.abs(event.amount))} $CUTEDSL
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              ) : (
                <div className="space-y-5">
                  <div className="rounded-2xl border border-pink-100 bg-white/80 p-5">
                    <div className="mb-4 flex items-center gap-2">
                      <CreditCard size={18} className="text-pink-500" />
                      <div>
                        <div className="text-sm font-bold text-slate-800">Pay by card</div>
                        <div className="text-xs text-slate-500">Create an account or log in first.</div>
                      </div>
                    </div>
                    <div className="grid gap-3">
                      <input
                        type="email"
                        value={emailInput}
                        data-testid="home-email"
                        onChange={(e) => setEmailInput(e.target.value)}
                        className="w-full rounded-xl border border-slate-200 px-4 py-3 text-sm outline-none focus:border-pink-400 focus:ring-2 focus:ring-pink-200"
                        placeholder="you@example.com"
                      />
                      <input
                        type="password"
                        value={passwordInput}
                        data-testid="home-password"
                        onChange={(e) => setPasswordInput(e.target.value)}
                        onKeyDown={(e) => e.key === 'Enter' && createStripeCheckout()}
                        className="w-full rounded-xl border border-slate-200 px-4 py-3 text-sm outline-none focus:border-pink-400 focus:ring-2 focus:ring-pink-200"
                        placeholder="8+ character password"
                      />
                      <button
                        onClick={loginWithEmailPassword}
                        disabled={authLoading || !isValidEmail(emailInput) || passwordInput.length < 8}
                        data-testid="home-email-continue"
                        className="inline-flex items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-pink-400 to-purple-400 px-4 py-3 text-sm font-bold text-white disabled:opacity-50"
                      >
                        {authLoading ? <RefreshCw size={16} className="animate-spin" /> : <Mail size={16} />}
                        Continue with email
                      </button>
                    </div>
                    {(authStatus || stripeStatus) && (
                      <div className={`mt-3 rounded-lg px-3 py-2 text-sm font-medium ${(authStatus || stripeStatus || '').toLowerCase().includes('fail') || (authStatus || stripeStatus || '').toLowerCase().includes('required') ? 'bg-red-50 text-red-600' : 'bg-green-50 text-green-600'}`}>
                        {authStatus || stripeStatus}
                      </div>
                    )}
                  </div>

                  <div className="rounded-2xl border border-dashed border-purple-200 bg-purple-50/60 p-5 text-center">
                    <p className="mb-4 text-sm font-medium text-slate-600">Prefer SOL or token deposits? Connect a Solana wallet.</p>
                    <button
                      onClick={connectWallet}
                      disabled={connectingWallet}
                      className="inline-flex items-center gap-2 rounded-full bg-slate-900 px-6 py-3 text-sm font-bold text-white disabled:opacity-50"
                    >
                      {connectingWallet ? <RefreshCw size={18} className="animate-spin" /> : <Wallet size={18} />}
                      Connect wallet
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </section>

      {/* API Docs */}
      <section id="api-docs" className="py-24 relative z-10">
        <div className="absolute inset-0 bg-slate-50/90 -z-10"></div>
        <div className="max-w-7xl mx-auto px-6">
          <div className="text-center mb-16">
            <h2 className="font-fredoka text-4xl lg:text-5xl font-bold text-slate-800 mb-4">API Reference</h2>
            <p className="text-lg text-slate-700 max-w-2xl mx-auto font-medium">One endpoint, one key, every model.</p>
          </div>

          {/* API Key display */}
          {apiKey && (
            <div className="bg-white p-6 rounded-2xl shadow-sm border border-indigo-200 mb-8">
              <div className="flex items-center justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-bold text-slate-600 mb-1">Your API Key</div>
                  <code className="block truncate text-sm bg-slate-100 px-3 py-2 rounded-lg font-mono">
                    {showApiKey ? apiKey : `${apiKey.slice(0, 8)}${'•'.repeat(20)}`}
                  </code>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  <button
                    type="button"
                    onClick={() => setShowApiKey(!showApiKey)}
                    className="p-2 hover:bg-slate-100 rounded-lg text-slate-400"
                    aria-label={showApiKey ? 'Hide API key' : 'Show API key'}
                  >
                    {showApiKey ? <EyeOff size={18} /> : <Eye size={18} />}
                  </button>
                  <button onClick={() => { navigator.clipboard.writeText(apiKey); setCopied(true); setTimeout(() => setCopied(false), 2000); }} className="p-2 hover:bg-slate-100 rounded-lg">
                    {copied ? <Check size={18} className="text-green-500" /> : <Copy size={18} className="text-slate-400" />}
                  </button>
                </div>
              </div>
              <p className="text-xs text-slate-400 mt-2">Use as: <code className="bg-slate-100 px-1 rounded">Authorization: Bearer {'<key>'}</code></p>
            </div>
          )}

          {/* Quick example */}
          <div className="bg-white p-6 rounded-2xl shadow-sm border border-slate-100 mb-8">
            <CodeBlock language="bash" className="text-xs p-4 rounded-lg shadow-none" code={`curl -X POST https://cutedsl.cc/api/service \\
  -H "Authorization: Bearer ${apiKey || 'YOUR_API_KEY'}" \\
  -H "Content-Type: application/json" \\
  -d '{"service": "zimage", "prompt": "a cute fairy in a forest", "width": 1024}'`} />
          </div>

          {/* Preview cards */}
          <div className="grid md:grid-cols-3 gap-4 mb-10">
            {[
              { name: 'Z-Image', slug: 'zimage', icon: <ImageIcon size={18} className="text-pink-500" />, desc: 'Text-to-image generation' },
              { name: 'Chronos-2', slug: 'chronos2', icon: <LineChart size={18} className="text-cyan-500" />, desc: 'Time series forecasting' },
              { name: 'Kokoro TTS', slug: 'tts', icon: <Volume2 size={18} className="text-purple-500" />, desc: 'Text-to-speech synthesis' },
            ].map(s => (
              <Link key={s.slug} href={`/docs/${s.slug}`} className="bg-white p-5 rounded-2xl shadow-sm border border-slate-100 hover:border-pink-300 hover:shadow-md transition-all group">
                <div className="flex items-center gap-2 mb-2">
                  {s.icon}
                  <h3 className="font-bold text-slate-800 group-hover:text-pink-600 transition-colors">{s.name}</h3>
                </div>
                <p className="text-sm text-slate-500">{s.desc}</p>
              </Link>
            ))}
          </div>

          <div className="text-center">
            <Link href="/docs" className="inline-flex items-center gap-2 bg-gradient-to-r from-pink-400 to-purple-400 text-white font-bold px-8 py-3 rounded-full shadow-lg hover:shadow-pink-300/50 hover:scale-105 transition-all">
              View Full API Docs <ArrowRight size={18} />
            </Link>
            <p className="text-sm text-slate-500 mt-3">Every service, with live playgrounds and copy-paste examples</p>
          </div>
        </div>
      </section>

      {/* Tokenomics */}
      <section id="token" className="py-24 bg-slate-900 text-white relative z-10 overflow-hidden">
        <div className="absolute inset-0 opacity-20 mix-blend-overlay" style={{ backgroundImage: `url(${IMG_BASE}/token-bg.webp)`, backgroundSize: 'cover' }}></div>
        <div className="absolute top-0 left-0 w-full h-full bg-gradient-to-b from-transparent to-pink-900/80"></div>
        
        <div className="max-w-4xl mx-auto px-6 text-center relative z-10">
          <Coins size={64} className="text-yellow-400 mx-auto mb-8" />
          <h2 className="font-fredoka text-5xl lg:text-6xl font-bold mb-6">Powered by $CUTEDSL</h2>
          <p className="text-xl text-slate-200 mb-10 font-medium">
            Pay for AI inference with <span className="text-pink-400 font-bold text-2xl">$CUTEDSL</span> on Solana. First-party models (zimage, chronos2, TTS) are priced at the token&apos;s all-time high &mdash; so early holders get cheaper inference forever. The more $CUTEDSL grows, the better your rate locks in.
          </p>
          
          <div className="bg-white/10 border border-white/20 rounded-3xl p-8 mb-10">
            <div className="grid grid-cols-1 md:grid-cols-4 gap-8">
              <div>
                <div className="text-4xl font-bold text-pink-400 mb-2 font-fredoka">
                  {cutePrice > 0 ? `$${cutePrice < 0.01 ? cutePrice.toFixed(6) : cutePrice.toFixed(4)}` : '...'}
                </div>
                <div className="text-slate-300">$CUTEDSL Price</div>
              </div>
              <div>
                <div className="text-4xl font-bold text-pink-400 mb-2 font-fredoka">100%</div>
                <div className="text-slate-300">Utility Driven</div>
              </div>
              <div>
                <div className="text-4xl font-bold text-cyan-400 mb-2 font-fredoka">0%</div>
                <div className="text-slate-300">Taxes</div>
              </div>
              <div>
                <div className="text-4xl font-bold text-yellow-400 mb-2 font-fredoka">SOL</div>
                <div className="text-slate-300">Network</div>
              </div>
            </div>
          </div>

          <a 
            href="https://bags.fm/D322k7ykdgCmNGUZL5XvsgZXdHU4ks8iGoWtfrnmBAGS" 
            target="_blank" 
            rel="noopener noreferrer"
            className="inline-flex items-center gap-3 bg-gradient-to-r from-pink-500 to-purple-500 text-white font-bold text-xl px-10 py-5 rounded-full shadow-[0_0_30px_rgba(236,72,153,0.5)] hover:scale-105 transition-transform"
          >
            <Coins size={24} />
            Buy $CUTEDSL on bags.fm
          </a>
        </div>
      </section>

      {/* Applied AI NZ Section */}
      <section id="applied-ai-nz" className="py-24 relative z-10 bg-slate-50/95 border-t border-slate-200">
        <div className="max-w-7xl mx-auto px-6">
          <div className="text-center mb-16">
            <a href="https://app.nz" target="_blank" rel="noopener noreferrer" className="inline-block bg-indigo-100 text-indigo-700 px-4 py-1 rounded-full font-bold text-sm mb-4 hover:bg-indigo-200 transition-colors">Applied AI NZ</a>
            <h2 className="font-fredoka text-4xl lg:text-5xl font-bold text-slate-800 mb-6">Our Ecosystem</h2>
            <p className="text-lg text-slate-600 max-w-3xl mx-auto">
              Cute DSL is part of a broader ecosystem of cutting-edge AI and technology products developed by <a href="https://app.nz" target="_blank" rel="noopener noreferrer" className="text-indigo-600 hover:text-indigo-800 underline">Applied AI NZ</a>.
            </p>
          </div>

          {/* Flagship Products */}
          <h3 className="text-2xl font-bold text-slate-800 mb-8 border-b border-slate-200 pb-2">Flagship Products</h3>
          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6 mb-16">
            <div className="bg-white p-6 rounded-2xl shadow-sm border border-slate-100 hover:shadow-md transition-shadow">
              <div className="flex justify-between items-start mb-4">
                <a href="https://dictatorflow.com" target="_blank" rel="noopener noreferrer" className="font-bold text-xl text-slate-800 hover:text-indigo-600 transition-colors">Dictatorflow.com</a>
                <Mic className="text-indigo-500" size={20} />
              </div>
              <p className="text-slate-600 text-sm mb-4">Speak to your computer. Advanced voice control and dictation.</p>
            </div>
            
            <div className="bg-white p-6 rounded-2xl shadow-sm border border-slate-100 hover:shadow-md transition-shadow">
              <div className="flex justify-between items-start mb-4">
                <a href="https://netwrck.com" target="_blank" rel="noopener noreferrer" className="font-bold text-xl text-slate-800 hover:text-pink-600 transition-colors">Netwrck.com</a>
                <Users className="text-pink-500" size={20} />
              </div>
              <p className="text-slate-600 text-sm mb-4">Social AI Community Network. Interact with advanced AI chatbots and create immersive illustrated stories voiced by AI agents.</p>
              <div className="flex gap-2 flex-wrap text-xs text-slate-500 font-medium">
                <span className="bg-slate-100 px-2 py-1 rounded">PyTorch</span>
                <span className="bg-slate-100 px-2 py-1 rounded">AI Agents</span>
                <span className="bg-slate-100 px-2 py-1 rounded">Gen Audio</span>
              </div>
            </div>

            <div className="bg-white p-6 rounded-2xl shadow-sm border border-slate-100 hover:shadow-md transition-shadow">
              <div className="flex justify-between items-start mb-4">
                <a href="https://ebank.nz" target="_blank" rel="noopener noreferrer" className="font-bold text-xl text-slate-800 hover:text-cyan-600 transition-colors">eBank.nz</a>
                <ImageIcon className="text-cyan-500" size={20} />
              </div>
              <p className="text-slate-600 text-sm mb-4">Affordable AI Art Generator. State-of-the-art generative art platform creating HD visuals using diffusion models and LoRAs.</p>
              <div className="flex gap-2 flex-wrap text-xs text-slate-500 font-medium">
                <span className="bg-slate-100 px-2 py-1 rounded">Stable Diffusion</span>
                <span className="bg-slate-100 px-2 py-1 rounded">CLIP</span>
              </div>
            </div>

            <div className="bg-white p-6 rounded-2xl shadow-sm border border-slate-100 hover:shadow-md transition-shadow">
              <div className="flex justify-between items-start mb-4">
                <a href="https://helix.app.nz" target="_blank" rel="noopener noreferrer" className="font-bold text-xl text-slate-800 hover:text-emerald-600 transition-colors">Helix.app.nz</a>
                <Database className="text-emerald-500" size={20} />
              </div>
              <p className="text-slate-600 text-sm mb-4">The AI Data Scientist. Interprets complex datasets, generates insights, and automates reporting with human-like reasoning.</p>
              <div className="flex gap-2 flex-wrap text-xs text-slate-500 font-medium">
                <span className="bg-slate-100 px-2 py-1 rounded">LLMs</span>
                <span className="bg-slate-100 px-2 py-1 rounded">Data Analytics</span>
              </div>
            </div>

            <div className="bg-white p-6 rounded-2xl shadow-sm border border-slate-100 hover:shadow-md transition-shadow">
              <div className="flex justify-between items-start mb-4">
                <a href="https://bitbank.nz" target="_blank" rel="noopener noreferrer" className="font-bold text-xl text-slate-800 hover:text-orange-600 transition-colors">BitBank.nz</a>
                <LineChart className="text-orange-500" size={20} />
              </div>
              <p className="text-slate-600 text-sm mb-4">Live Crypto Forecasting. Institutional-grade forecasting platform providing actionable predictions backed by real-time AI analysis.</p>
              <div className="flex gap-2 flex-wrap text-xs text-slate-500 font-medium">
                <span className="bg-slate-100 px-2 py-1 rounded">Predictive Modeling</span>
              </div>
            </div>
          </div>

          {/* Innovation Lab */}
          <h3 className="text-2xl font-bold text-slate-800 mb-8 border-b border-slate-200 pb-2">Innovation Lab</h3>
          <div className="grid md:grid-cols-3 gap-6 mb-16">
            <div className="bg-slate-100/50 p-6 rounded-2xl border border-slate-200">
              <a href="https://text-generator.io" target="_blank" rel="noopener noreferrer" className="font-bold text-lg text-slate-800 mb-2 flex items-center gap-2 hover:text-indigo-600 transition-colors"><Code size={16}/> Text-Generator.io</a>
              <p className="text-slate-600 text-sm">Secure, multilingual text and code generation powered by massive neural networks.</p>
            </div>
            <div className="bg-slate-100/50 p-6 rounded-2xl border border-slate-200">
              <a href="https://netwrck.com" target="_blank" rel="noopener noreferrer" className="font-bold text-lg text-slate-800 mb-2 flex items-center gap-2 hover:text-indigo-600 transition-colors"><Cpu size={16}/> StackHack</a>
              <p className="text-slate-600 text-sm">Analyze and breakdown any technology stack instantly using Large Language Models.</p>
            </div>
            <div className="bg-slate-100/50 p-6 rounded-2xl border border-slate-200">
              <a href="https://sitesim.net" target="_blank" rel="noopener noreferrer" className="font-bold text-lg text-slate-800 mb-2 flex items-center gap-2 hover:text-indigo-600 transition-colors"><Layout size={16}/> SiteSim</a>
              <p className="text-slate-600 text-sm">Dream it, prompt it, browse it. Create entire simulated websites using LLMs on the fly.</p>
            </div>
          </div>

          {/* More Products */}
          <h3 className="text-2xl font-bold text-slate-800 mb-8 border-b border-slate-200 pb-2">More Products</h3>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
            <div className="bg-white p-4 rounded-xl text-center border border-slate-100 shadow-sm">
              <a href="https://bigmultiplayerchess.com" target="_blank" rel="noopener noreferrer" className="font-bold text-slate-800 text-sm hover:text-indigo-600 transition-colors">BigMultiplayerChess</a>
              <p className="text-xs text-slate-500 mt-1">Large-scale AI chess game</p>
            </div>
            <div className="bg-white p-4 rounded-xl text-center border border-slate-100 shadow-sm">
              <a href="https://evangeler.com" target="_blank" rel="noopener noreferrer" className="font-bold text-slate-800 text-sm hover:text-indigo-600 transition-colors">Evangeler.com</a>
              <p className="text-xs text-slate-500 mt-1">Affiliate marketing platform</p>
            </div>
            <div className="bg-white p-4 rounded-xl text-center border border-slate-100 shadow-sm">
              <a href="https://rewordgame.com" target="_blank" rel="noopener noreferrer" className="font-bold text-slate-800 text-sm hover:text-indigo-600 transition-colors">reWord Game</a>
              <p className="text-xs text-slate-500 mt-1">AI word puzzle game</p>
            </div>
            <div className="bg-white p-4 rounded-xl text-center border border-slate-100 shadow-sm">
              <a href="https://how.nz" target="_blank" rel="noopener noreferrer" className="font-bold text-slate-800 text-sm hover:text-indigo-600 transition-colors">How.nz</a>
              <p className="text-xs text-slate-500 mt-1">Technical deep dives</p>
            </div>
            <div className="bg-white p-4 rounded-xl text-center border border-slate-100 shadow-sm">
              <a href="https://ring.nz" target="_blank" rel="noopener noreferrer" className="font-bold text-slate-800 text-sm hover:text-indigo-600 transition-colors">Ring.nz</a>
              <p className="text-xs text-slate-500 mt-1">Search engine</p>
            </div>
          </div>
        </div>
      </section>

      <SiteFooter />
    </div>
  );
}
