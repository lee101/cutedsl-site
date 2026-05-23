'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import {
  Sparkles, Wand2, Image as ImageIcon, LineChart, Coins, Heart, Star, Zap,
  Mic, Volume2, BookOpen, Cloud, Code, Globe, Cpu, Database, Layout, Search, Gamepad2, Users,
  Wallet, ArrowRight, RefreshCw, Copy, Check, LogOut, X, Key, Mail, Eye, EyeOff, CreditCard
} from 'lucide-react';
import Image from 'next/image';
import Link from 'next/link';
import { CodeBlock } from '@/lib/code-block';

const API_BASE = '/api';
const IMG_BASE = '/images';

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
  const [testMode, setTestMode] = useState(false);
  const [testResults, setTestResults] = useState<{route: string; status: string; ms: number}[]>([]);
  const [email, setEmail] = useState<string | null>(null);
  const [emailInput, setEmailInput] = useState('');
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
  const embeddedCheckoutRef = useRef<StripeEmbeddedCheckout | null>(null);

  useEffect(() => {
    setClientOrigin(window.location.origin);
  }, []);

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
      const res = await fetch(`${API_BASE}/balance?wallet=${wallet}`);
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
      const res = await fetch(`${API_BASE}/billing-history?wallet=${wallet}`);
      const data = await res.json();
      setBillingHistory(data.events || []);
    } catch {}
  }, []);

  useEffect(() => {
    if (!embeddedCheckoutClientSecret || !stripePublishableKey || !embeddedCheckoutElementRef.current) return;

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
            setStripeStatus('Payment complete. Credits will appear after Stripe confirms the checkout.');
            setEmbeddedCheckoutClientSecret('');
            if (walletAddress) {
              fetchBalance(walletAddress);
              fetchHistory(walletAddress);
            }
          },
        });
        if (cancelled) {
          checkout.destroy();
          return;
        }
        embeddedCheckoutRef.current = checkout;
        checkout.mount(embeddedCheckoutElementRef.current!);
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
  }, [embeddedCheckoutClientSecret, stripePublishableKey, walletAddress, fetchBalance, fetchHistory]);

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
    const saved = localStorage.getItem('cutedsl_wallet');
    if (saved) setWalletAddress(saved);
    const savedKey = localStorage.getItem('cutedsl_api_key');
    if (savedKey) setApiKey(savedKey);
    const savedEmail = localStorage.getItem('cutedsl_email');
    if (savedEmail) setEmail(savedEmail);
    // ?test=true triggers e2e API test
    if (typeof window !== 'undefined' && new URLSearchParams(window.location.search).get('test') === 'true') {
      setTestMode(true);
      runE2ETests();
    }
    if (typeof window !== 'undefined') {
      const payment = new URLSearchParams(window.location.search).get('payment');
      if (payment === 'success') setStripeStatus('Payment received. Credits will appear after Stripe confirms the checkout.');
      if (payment === 'cancel') setStripeStatus('Stripe checkout was cancelled.');
    }
  }, []);

  const runE2ETests = async () => {
    const results: {route: string; status: string; ms: number}[] = [];
    const test = async (route: string, opts?: RequestInit) => {
      const t0 = Date.now();
      try {
        const res = await fetch(`${API_BASE}${route}`, opts);
        const ms = Date.now() - t0;
        const ok = res.status < 500;
        results.push({ route, status: ok ? `${res.status} OK` : `${res.status} FAIL`, ms });
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
  };

  const tryImageGen = async () => {
    if (!apiKey) return;
    setDemoLoading(true);
    setDemoResult(null);
    try {
      const res = await fetch(`${API_BASE}/service`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${apiKey}` },
        body: JSON.stringify({ prompt: demoPrompt, width: 512, height: 512, num_steps: 4 }),
      });
      const data = await res.json();
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

  const connectWallet = async () => {
    setConnectingWallet(true);
    try {
      // Check for Phantom wallet
      const solana = (window as any).solana;
      const registerWallet = async (addr: string) => {
        const res = await fetch(`${API_BASE}/auth/wallet`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ wallet_address: addr }),
        });
        const data = await res.json();
        if (data.api_key) {
          setApiKey(data.api_key);
          localStorage.setItem('cutedsl_api_key', data.api_key);
        }
        if (data.user?.email) {
          setEmail(data.user.email);
          localStorage.setItem('cutedsl_email', data.user.email);
        }
      };

      if (solana?.isPhantom) {
        const resp = await solana.connect();
        const addr = resp.publicKey.toString();
        setWalletAddress(addr);
        localStorage.setItem('cutedsl_wallet', addr);
        await registerWallet(addr);
      } else {
        // Fallback: prompt for wallet address
        const addr = prompt('Enter your Solana wallet address:');
        if (addr && addr.length > 30) {
          setWalletAddress(addr);
          localStorage.setItem('cutedsl_wallet', addr);
          await registerWallet(addr);
        }
      }
    } catch (err) {
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
    setEmailSaved(false);
    localStorage.removeItem('cutedsl_wallet');
    localStorage.removeItem('cutedsl_api_key');
    localStorage.removeItem('cutedsl_email');
    try {
      const solana = (window as any).solana;
      if (solana?.isPhantom) solana.disconnect();
    } catch {}
  };

  const saveEmail = async () => {
    if (!walletAddress || !emailInput.includes('@')) return;
    setEmailSaving(true);
    try {
      const res = await fetch(`${API_BASE}/auth/email`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ wallet_address: walletAddress, email: emailInput }),
      });
      const data = await res.json();
      if (data.success) {
        setEmail(emailInput);
        localStorage.setItem('cutedsl_email', emailInput);
        setEmailSaved(true);
        setTimeout(() => setEmailSaved(false), 3000);
      }
    } catch (err) {
      console.error('Email save error:', err);
    } finally {
      setEmailSaving(false);
    }
  };

  const createDeposit = async () => {
    if (!walletAddress || !depositAmount) return;
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

  const createStripeCheckout = async () => {
    if (!walletAddress || !stripeAmount) return;
    setStripeLoading(true);
    setStripeStatus(null);
    try {
      const amount = parseFloat(stripeAmount);
      const res = await fetch(`${API_BASE}/stripe-checkout`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          wallet_address: walletAddress,
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
        setStripeStatus('Complete the secure Stripe checkout below.');
        return;
      }
      if (data.url) {
        window.location.href = data.url;
        return;
      }
      throw new Error('Stripe checkout response did not include a client secret');
    } catch (err: any) {
      setStripeStatus(err?.message || 'Stripe checkout failed');
    } finally {
      setStripeLoading(false);
    }
  };

  const saveAutotopupSettings = async () => {
    if (!walletAddress) return;
    setAutotopupSaving(true);
    setStripeStatus(null);
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
    if (!walletAddress || !buySolAmount || buyLoading) return;
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

  const formatCute = (n: number) => {
    if (n >= 1000000) return `${(n / 1000000).toFixed(1)}M`;
    if (n >= 1000) return `${(n / 1000).toFixed(1)}K`;
    return n.toFixed(0);
  };

  return (
      <div className="min-h-screen overflow-hidden relative selection:bg-pink-300 selection:text-pink-900">
        {/* CSS-only background avoids React timers and extra LCP-network contention. */}
        <div className="fixed inset-0 -z-20 bg-[linear-gradient(135deg,#fff1f7_0%,#f5f3ff_48%,#ecfeff_100%)]" />

      {/* Navigation */}
      <header>
      <nav aria-label="Main navigation" className="w-full p-6 flex justify-between items-center max-w-7xl mx-auto relative z-10">
        <Link href="/" className="flex items-center gap-2">
          <Image src={`${IMG_BASE}/logo.webp`} alt="CuteDSL" width={40} height={40} className="rounded-lg" />
          <span className="font-fredoka text-3xl font-bold text-pink-600 tracking-wide">CuteDSL</span>
        </Link>
        <div className="hidden md:flex gap-5 font-bold text-slate-700">
          <Link href="#models" className="hover:text-pink-500 transition-colors">Models</Link>
          <Link href="/gallery" className="hover:text-pink-500 transition-colors">Gallery</Link>
          <Link href="/search" className="hover:text-pink-500 transition-colors">Search</Link>
          <Link href="#training" className="hover:text-purple-500 transition-colors">Training</Link>
          <Link href="/docs" className="hover:text-blue-500 transition-colors">API Docs</Link>
          <Link href="/account" className="hover:text-emerald-600 transition-colors">Account</Link>
          <Link href="#token" className="hover:text-cyan-500 transition-colors">$CUTEDSL</Link>
          <Link href="/evals" className="hover:text-cyan-500 transition-colors">Evals</Link>
          <Link href="/blog" className="hover:text-orange-500 transition-colors">Blog</Link>
        </div>
        <div className="flex items-center gap-3">
          {walletAddress ? (
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
            <Link
              href="/account"
              className="bg-gradient-to-r from-pink-400 to-purple-400 text-white font-bold px-6 py-2 rounded-full shadow-lg hover:shadow-pink-300/50 hover:scale-105 transition-all flex items-center gap-2"
            >
              <Wallet size={18} />
              Login / Pay
            </Link>
          )}
        </div>
      </nav>
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

      {/* Hero Section */}
      <main className="max-w-7xl mx-auto px-6 pt-12 pb-24 relative z-10">
        <div className="flex flex-col lg:flex-row items-center gap-16">
          <div
            className="flex-1 text-center lg:text-left relative"
          >
            <div className="absolute -top-12 -left-12 hidden lg:block opacity-80">
              <Image src={`${IMG_BASE}/avatar.webp`} alt="" width={100} height={100} loading="lazy" className="rounded-full border-4 border-pink-200 shadow-lg" />
            </div>

            <h1 className="font-fredoka text-6xl lg:text-8xl font-bold mb-6 leading-tight text-slate-800">
              Fast AI APIs, <span className="text-gradient-cute">Cute</span> Pricing
            </h1>
            <p className="text-xl text-slate-700 mb-10 max-w-2xl mx-auto lg:mx-0 font-medium bg-white/70 p-4 rounded-2xl border border-white/80">
              CuteDSL is a developer API for image generation, forecasting, speech, chat, captioning, and custom LoRAs. Use card-funded credits or $CUTEDSL on Solana, with accelerated first-party models under the hood.
            </p>
            <div className="flex flex-col sm:flex-row gap-4 justify-center lg:justify-start flex-wrap">
              <a href="#models" className="bg-gradient-to-r from-pink-400 to-purple-400 text-white font-bold text-lg px-8 py-4 rounded-full shadow-lg hover:shadow-xl hover:scale-105 transition-all flex items-center justify-center gap-2">
                <Wand2 size={20} />
                Explore Models
              </a>
              <Link href="/gallery" prefetch={false} className="bg-white text-slate-700 font-bold text-lg px-8 py-4 rounded-full shadow-lg hover:shadow-xl hover:scale-105 transition-all flex items-center justify-center gap-2 border-2 border-pink-100">
                <Sparkles size={20} className="text-pink-500" />
                Art Gallery
              </Link>
              <a href="#api" className="bg-white text-slate-700 font-bold text-lg px-8 py-4 rounded-full shadow-lg hover:shadow-xl hover:scale-105 transition-all flex items-center justify-center gap-2 border-2 border-pink-100">
                <Code size={20} className="text-blue-500" />
                API Docs
              </a>
              <Link href="/account" className="bg-slate-900 text-white font-bold text-lg px-8 py-4 rounded-full shadow-lg hover:shadow-xl hover:scale-105 transition-all flex items-center justify-center gap-2">
                <CreditCard size={20} />
                Account & Billing
              </Link>
            </div>
          </div>
          
          <div
            className="flex-1 relative"
          >
            <div className="relative w-full max-w-lg mx-auto aspect-square">
              <div className="absolute inset-0 bg-gradient-to-tr from-pink-200 to-cyan-200 rounded-full opacity-60"></div>
              <Image
                src={`${IMG_BASE}/hero.webp`}
                alt="CuteDSL AI model acceleration platform"
                fill
                priority
                sizes="(min-width: 1024px) 38vw, 90vw"
                className="object-cover rounded-full border-8 border-white/50 shadow-2xl"
              />
              {/* Floating badges */}
              <div className="absolute -top-6 -right-6 glass-card p-4 rounded-2xl flex items-center gap-3">
                <div className="bg-pink-100 p-2 rounded-full text-pink-500"><ImageIcon size={24} /></div>
                <div className="font-bold text-slate-700">zimage</div>
              </div>
              <div className="absolute -bottom-10 left-10 glass-card p-4 rounded-2xl flex items-center gap-3">
                <div className="bg-cyan-100 p-2 rounded-full text-cyan-500"><LineChart size={24} /></div>
                <div className="font-bold text-slate-700">chronos2</div>
              </div>
            </div>
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
            <p className="text-lg text-slate-700 max-w-2xl mx-auto font-medium">Custom fused Triton kernels and kernel-level optimizations for maximum throughput.</p>
          </div>

          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6">
            <Link href="/docs/zimage">
            <div className="glass-card card-hover p-6 rounded-3xl relative overflow-hidden group bg-white/70 cursor-pointer">
              <div className="bg-pink-100 w-14 h-14 rounded-2xl flex items-center justify-center text-pink-500 mb-4 shadow-inner">
                <ImageIcon size={28} />
              </div>
              <h3 className="font-fredoka text-2xl font-bold text-slate-800 mb-2 group-hover:text-pink-600 transition-colors">zimage</h3>
              <p className="text-slate-600 mb-4 text-sm">
                CuteDSL-accelerated Z-Image Turbo with fused QK-norm+RoPE kernel and custom Triton kernels. 2x faster transformer blocks via kernel fusion and NVFP4 quantization on RTX 5090.
              </p>
              <div className="flex items-center gap-2 text-pink-500 font-bold text-sm mt-auto">
                <Zap size={16} /> {getServicePrice('zimage') > 0 ? `${formatCute(getServicePrice('zimage'))} $CUTEDSL` : '1000 $CUTEDSL'} / gen
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
                SOTA time series forecasting. CuteDSL-accelerated Chronos-2 with 27x faster inference via 8 custom Triton kernels, fused preprocessing, and torch.compile. Quantile predictions for uncertainty estimation.
              </p>
              <div className="flex items-center gap-2 text-cyan-500 font-bold text-sm mt-auto">
                <Zap size={16} /> {getServicePrice('chronos2') > 0 ? `${formatCute(getServicePrice('chronos2'))} $CUTEDSL` : '500 $CUTEDSL'} / forecast
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
                Text-to-Speech with 20+ cute voices and languages. Beautiful, natural voices for your applications.
              </p>
              <div className="flex items-center gap-2 text-purple-500 font-bold text-sm mt-auto">
                <Zap size={16} /> {getServicePrice('tts') > 0 ? `${formatCute(getServicePrice('tts'))} $CUTEDSL` : '100 $CUTEDSL'} / 100 chars
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
                Gemma4-powered audio transcription. High-accuracy speech recognition for your applications.
              </p>
              <div className="flex items-center gap-2 text-blue-500 font-bold text-sm mt-auto">
                <Zap size={16} /> {getServicePrice('stt') > 0 ? `${formatCute(getServicePrice('stt'))} $CUTEDSL` : '200 $CUTEDSL'} / minute
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
                Google Gemma4 26B multimodal LLM. Text and vision understanding with OpenAI-compatible API. Powered by text-generator.io.
              </p>
              <div className="flex items-center gap-2 text-emerald-500 font-bold text-sm mt-auto">
                <Zap size={16} /> {getServicePrice('gemma4') > 0 ? `${formatCute(getServicePrice('gemma4'))} $CUTEDSL` : '50 $CUTEDSL'} / request
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
                GitBase-powered image captioning. Generate accurate descriptions of any image for accessibility, search, or AI pipelines.
              </p>
              <div className="flex items-center gap-2 text-orange-500 font-bold text-sm mt-auto">
                <Zap size={16} /> {getServicePrice('caption') > 0 ? `${formatCute(getServicePrice('caption'))} $CUTEDSL` : '50 $CUTEDSL'} / image
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
                Text-to-video generation via LTX 2.3. Generate 6-second 1080p videos from text prompts. Powered by fal.ai.
              </p>
              <div className="flex items-center gap-2 text-red-500 font-bold text-sm mt-auto">
                <Zap size={16} /> {getServicePrice('ltx_video') > 0 ? `${formatCute(getServicePrice('ltx_video'))} $CUTEDSL` : '300 $CUTEDSL'} / video
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
                Fast image generation via Flux Schnell. 4-step inference for quick 1024x1024 images. Also available through eBank.nz.
              </p>
              <div className="flex items-center gap-2 text-indigo-500 font-bold text-sm mt-auto">
                <Zap size={16} /> {getServicePrice('flux_image') > 0 ? `${formatCute(getServicePrice('flux_image'))} $CUTEDSL` : '40 $CUTEDSL'} / image
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
              <p className="text-slate-500 mb-6 text-sm">Generate an image with your API key. This calls <code className="bg-slate-100 px-1 rounded">POST /api/service</code> with your credits.</p>
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
              <h2 className="font-fredoka text-4xl lg:text-5xl font-bold text-slate-800 mb-6">Training API</h2>
              <p className="text-lg text-slate-700 mb-6 font-medium">
                Fine-tune your own custom LoRAs for both <strong className="text-pink-600">zimage</strong> and <strong className="text-cyan-600">chronos2</strong> via our training API.
              </p>
              <p className="text-md text-slate-600 mb-8">
                Upload your dataset and we&apos;ll train a personalized model for you, ready to query via our inference API.
              </p>
              <ul className="space-y-4 mb-8">
                <li className="flex items-center gap-3 text-slate-700 font-medium">
                  <Star className="text-yellow-500" size={20} /> Fast training on high-end GPUs
                </li>
                <li className="flex items-center gap-3 text-slate-700 font-medium">
                  <Star className="text-yellow-500" size={20} /> LoRA support for Image Gen (zimage)
                </li>
                <li className="flex items-center gap-3 text-slate-700 font-medium">
                  <Star className="text-yellow-500" size={20} /> LoRA support for Time Series (chronos2)
                </li>
              </ul>
              <button className="bg-purple-500 text-white font-bold px-8 py-4 rounded-full shadow-lg hover:bg-purple-600 transition-colors">
                Start Training (5000 $CUTEDSL)
              </button>
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
            <p className="text-lg text-slate-700 max-w-2xl mx-auto font-medium">Integrate our models into your applications.</p>
          </div>

          <div className="grid md:grid-cols-2 gap-8">
            <div className="glass-card p-10 rounded-3xl bg-white/80">
              <div className="flex items-center gap-4 mb-6">
                <div className="bg-blue-100 p-4 rounded-2xl text-blue-600"><BookOpen size={32} /></div>
                <h3 className="font-fredoka text-3xl font-bold text-slate-800">API Usage Docs</h3>
              </div>
              <p className="text-slate-600 mb-8 text-lg">
                Comprehensive documentation on how to authenticate, call our models (zimage, chronos2, Kokoro TTS, STT, Gemma4, Image Caption), and manage your custom LoRAs.
              </p>
              <Link href="#api-docs" className="inline-flex items-center gap-2 text-blue-600 font-bold hover:text-blue-700">
                Read the Docs &rarr;
              </Link>
            </div>

            <div className="glass-card p-10 rounded-3xl bg-white/80" id="credits">
              <div className="flex items-center gap-4 mb-6">
                <div className="bg-yellow-100 p-4 rounded-2xl text-yellow-600"><Cloud size={32} /></div>
                <h3 className="font-fredoka text-3xl font-bold text-slate-800">Cloud Credits</h3>
              </div>

              {walletAddress ? (
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

                  {/* Email signup */}
                  {!email ? (
                    <div className="bg-gradient-to-r from-indigo-50 to-purple-50 p-5 rounded-2xl border border-indigo-200">
                      <div className="text-sm font-bold text-slate-600 mb-2">Get updates & API tips via email</div>
                      <div className="flex gap-2">
                        <input
                          type="email"
                          value={emailInput}
                          onChange={(e) => setEmailInput(e.target.value)}
                          onKeyDown={(e) => e.key === 'Enter' && saveEmail()}
                          className="flex-1 px-4 py-2.5 rounded-xl border border-slate-200 focus:border-indigo-400 focus:ring-2 focus:ring-indigo-200 outline-none text-sm"
                          placeholder="your@email.com"
                        />
                        <button
                          onClick={saveEmail}
                          disabled={emailSaving || !emailInput.includes('@')}
                          className="bg-gradient-to-r from-indigo-400 to-purple-400 text-white font-bold px-5 py-2.5 rounded-xl hover:scale-105 transition-transform disabled:opacity-50 text-sm"
                        >
                          {emailSaving ? <RefreshCw size={16} className="animate-spin" /> : emailSaved ? <Check size={16} /> : 'Save'}
                        </button>
                      </div>
                      <div className="text-xs text-slate-400 mt-2">We&apos;ll send you a 20-part onboarding series about our API, acceleration techniques, and tips.</div>
                    </div>
                  ) : (
                    <div className="flex items-center gap-2 text-sm text-slate-500 bg-indigo-50/50 px-4 py-2 rounded-xl">
                      <Check size={14} className="text-green-500" />
                      Signed up as {email}
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
                        {embeddedCheckoutClientSecret ? (
                          <div className="rounded-2xl border border-slate-200 bg-white p-3 shadow-sm" data-testid="embedded-checkout-container">
                            <div className="mb-3 flex items-center justify-between gap-3 px-1">
                              <div>
                                <div className="text-sm font-bold text-slate-700">Secure card checkout</div>
                                <div className="text-xs text-slate-400">Powered by Stripe</div>
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
                                onClick={createStripeCheckout}
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
                            disabled={autotopupSaving}
                            className="w-full bg-slate-800 text-white font-bold px-4 py-2.5 rounded-xl hover:bg-slate-700 transition-colors disabled:opacity-50"
                          >
                            {autotopupSaving ? 'Saving...' : 'Save auto top-up'}
                          </button>
                          {balance && !balance.has_payment_method && (
                            <div className="text-xs text-amber-600 bg-amber-50 px-3 py-2 rounded-lg">
                              Buy credits with Stripe once before enabling auto top-up.
                            </div>
                          )}
                        </div>

                        {stripeStatus && (
                          <div className={`text-sm font-medium px-3 py-2 rounded-lg ${stripeStatus.includes('failed') || stripeStatus.includes('Failed') || stripeStatus.includes('cancelled') || stripeStatus.includes('before enabling') ? 'bg-red-50 text-red-600' : 'bg-green-50 text-green-600'}`}>
                            {stripeStatus}
                          </div>
                        )}
                      </div>
                    ) : buyTab === 'buy' ? (
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
                <div className="text-center py-6">
                  <p className="text-slate-600 mb-6 text-lg">Connect your Solana wallet to deposit $CUTEDSL and start using AI services.</p>
                  <button
                    onClick={connectWallet}
                    disabled={connectingWallet}
                    className="bg-gradient-to-r from-pink-400 to-purple-400 text-white font-bold px-8 py-4 rounded-full hover:scale-105 transition-transform inline-flex items-center gap-2"
                  >
                    <Wallet size={20} />
                    {connectingWallet ? 'Connecting...' : 'Connect Wallet'}
                  </button>
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
            <p className="text-lg text-slate-700 max-w-2xl mx-auto font-medium">One unified endpoint for all services. Authenticate with your API key and start building.</p>
          </div>

          {/* API Key display */}
          {apiKey && (
            <div className="bg-white p-6 rounded-2xl shadow-sm border border-indigo-200 mb-8">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-sm font-bold text-slate-600 mb-1">Your API Key</div>
                  <code className="text-sm bg-slate-100 px-3 py-2 rounded-lg font-mono">{apiKey}</code>
                </div>
                <button onClick={() => { navigator.clipboard.writeText(apiKey); setCopied(true); setTimeout(() => setCopied(false), 2000); }} className="p-2 hover:bg-slate-100 rounded-lg">
                  {copied ? <Check size={18} className="text-green-500" /> : <Copy size={18} className="text-slate-400" />}
                </button>
              </div>
              <p className="text-xs text-slate-400 mt-2">Use as: <code className="bg-slate-100 px-1 rounded">Authorization: Bearer {apiKey}</code></p>
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
            <p className="text-sm text-slate-500 mt-3">9 services with interactive playgrounds, full parameter docs, and code examples</p>
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

      {/* Footer */}
      <footer className="bg-white/95 border-t border-pink-200 py-12 relative z-10">
        <div className="max-w-7xl mx-auto px-6">
          <div className="grid grid-cols-1 md:grid-cols-4 gap-8 mb-8">
            <div className="col-span-1 md:col-span-2">
              <div className="flex items-center gap-2 mb-4">
                <Image src={`${IMG_BASE}/logo.webp`} alt="CuteDSL" width={32} height={32} className="rounded-lg" />
                <span className="font-fredoka text-2xl font-bold text-slate-800">CuteDSL</span>
              </div>
              <p className="text-slate-500 font-medium max-w-sm">
                SOTA model acceleration &amp; inference platform. Part of the <a href="https://app.nz" target="_blank" rel="noopener noreferrer" className="text-indigo-500 hover:text-indigo-700 underline">Applied AI NZ</a> ecosystem.
              </p>
            </div>
            
            <div>
              <h4 className="font-bold text-slate-800 mb-4">Explore</h4>
              <ul className="space-y-2 text-slate-500 font-medium">
                <li><Link href="/gallery" className="hover:text-pink-500 transition-colors">AI Art Gallery</Link></li>
                <li><Link href="/search" className="hover:text-pink-500 transition-colors">Search Images</Link></li>
                <li><Link href="#models" className="hover:text-pink-500 transition-colors">Models (zimage, chronos2)</Link></li>
                <li><Link href="/evals" className="hover:text-cyan-500 transition-colors">Evals & Benchmarks</Link></li>
                <li><Link href="/blog" className="hover:text-purple-500 transition-colors">Blog</Link></li>
                <li><Link href="/docs" className="hover:text-blue-500 transition-colors">API Docs</Link></li>
                <li><a href="https://github.com/lee101/cutedsl" target="_blank" rel="noopener noreferrer" className="hover:text-slate-700 transition-colors">GitHub — lee101/cutedsl</a></li>
              </ul>
            </div>

            <div>
              <h4 className="font-bold text-slate-800 mb-4">Ecosystem</h4>
              <ul className="space-y-2 text-slate-500 font-medium">
                <li><a href="https://app.nz" target="_blank" rel="noopener noreferrer" className="hover:text-indigo-500 transition-colors">App.nz — Applied AI NZ</a></li>
                <li><a href="https://netwrck.com" target="_blank" rel="noopener noreferrer" className="hover:text-indigo-500 transition-colors">Netwrck.com</a></li>
                <li><a href="https://ebank.nz" target="_blank" rel="noopener noreferrer" className="hover:text-indigo-500 transition-colors">eBank.nz</a></li>
                <li><a href="https://helix.app.nz" target="_blank" rel="noopener noreferrer" className="hover:text-indigo-500 transition-colors">Helix.app.nz</a></li>
                <li><a href="https://bitbank.nz" target="_blank" rel="noopener noreferrer" className="hover:text-indigo-500 transition-colors">BitBank.nz</a></li>
                <li><a href="https://dictatorflow.com" target="_blank" rel="noopener noreferrer" className="hover:text-indigo-500 transition-colors">Dictatorflow.com</a></li>
              </ul>
            </div>
          </div>
          
          <div className="border-t border-slate-200 pt-8 flex flex-col md:flex-row justify-between items-center gap-4">
            <p className="text-slate-400 font-medium text-sm">© 2026 <a href="https://app.nz" target="_blank" rel="noopener noreferrer" className="hover:text-indigo-500 transition-colors">Applied AI NZ</a>. All rights reserved.</p>
            <div className="flex gap-4">
              <a href="https://x.com/leeleepenkman" target="_blank" rel="noopener noreferrer" className="text-slate-400 hover:text-pink-500 transition-colors">X</a>
              <a href="https://codex-infinity.com" target="_blank" rel="noopener noreferrer" className="text-slate-400 hover:text-cyan-500 transition-colors">Codex Infinity</a>
            </div>
          </div>
        </div>
      </footer>
    </div>
  );
}
