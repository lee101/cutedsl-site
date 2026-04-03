'use client';

import { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import {
  Sparkles, Wand2, Image as ImageIcon, LineChart, Coins, Heart, Star, Zap,
  Mic, Volume2, BookOpen, Cloud, Code, Globe, Cpu, Database, Layout, Search, Gamepad2, Users,
  Wallet, ArrowRight, RefreshCw, Copy, Check, LogOut
} from 'lucide-react';
import Image from 'next/image';
import Link from 'next/link';

const API_BASE = '/api';

const BACKGROUNDS = [
  "https://picsum.photos/seed/fairy-landscape1/1920/1080",
  "https://picsum.photos/seed/fairy-forest/1920/1080",
  "https://picsum.photos/seed/magic-castle/1920/1080",
  "https://picsum.photos/seed/enchanted-lake/1920/1080"
];

interface WalletBalance {
  wallet_address: string;
  credits: number;
  credits_usd: number;
  cute_price_usd: number;
  total_deposited: number;
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
  const [bgIndex, setBgIndex] = useState(0);
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

  useEffect(() => {
    const interval = setInterval(() => {
      setBgIndex((prev) => (prev + 1) % BACKGROUNDS.length);
    }, 6000);
    return () => clearInterval(interval);
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
    if (walletAddress) {
      fetchBalance(walletAddress);
      fetchHistory(walletAddress);
      const interval = setInterval(() => fetchBalance(walletAddress), 30000);
      return () => clearInterval(interval);
    }
  }, [walletAddress, fetchBalance, fetchHistory]);

  // Restore wallet from localStorage
  useEffect(() => {
    const saved = localStorage.getItem('cutedsl_wallet');
    if (saved) setWalletAddress(saved);
  }, []);

  const connectWallet = async () => {
    setConnectingWallet(true);
    try {
      // Check for Phantom wallet
      const solana = (window as any).solana;
      if (solana?.isPhantom) {
        const resp = await solana.connect();
        const addr = resp.publicKey.toString();
        setWalletAddress(addr);
        localStorage.setItem('cutedsl_wallet', addr);
        // Register with backend
        await fetch(`${API_BASE}/auth/wallet`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ wallet_address: addr }),
        });
      } else {
        // Fallback: prompt for wallet address
        const addr = prompt('Enter your Solana wallet address:');
        if (addr && addr.length > 30) {
          setWalletAddress(addr);
          localStorage.setItem('cutedsl_wallet', addr);
          await fetch(`${API_BASE}/auth/wallet`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ wallet_address: addr }),
          });
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
    localStorage.removeItem('cutedsl_wallet');
    try {
      const solana = (window as any).solana;
      if (solana?.isPhantom) solana.disconnect();
    } catch {}
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

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
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
      {/* Auto-changing Background */}
      <div className="fixed inset-0 -z-20 bg-slate-900">
        {BACKGROUNDS.map((bg, i) => (
          <div
            key={bg}
            className={`absolute inset-0 bg-cover bg-center transition-opacity duration-[3000ms] ease-in-out ${
              i === bgIndex ? 'opacity-40' : 'opacity-0'
            }`}
            style={{ backgroundImage: `url(${bg})` }}
          />
        ))}
        {/* Gradient overlay to ensure text readability */}
        <div className="absolute inset-0 bg-gradient-to-b from-pink-50/90 via-purple-50/80 to-cyan-50/90 backdrop-blur-[2px]" />
      </div>

      {/* Magical Background Elements */}
      <div className="fixed inset-0 -z-10 pointer-events-none">
        <div className="absolute top-10 left-10 text-pink-400 animate-sparkle" style={{ animationDelay: '0s' }}><Star size={24} /></div>
        <div className="absolute top-40 right-20 text-purple-400 animate-sparkle" style={{ animationDelay: '1s' }}><Sparkles size={32} /></div>
        <div className="absolute bottom-20 left-1/4 text-cyan-400 animate-sparkle" style={{ animationDelay: '2s' }}><Star size={20} /></div>
        <div className="absolute top-1/3 left-1/2 text-yellow-400 animate-sparkle" style={{ animationDelay: '0.5s' }}><Sparkles size={28} /></div>
      </div>

      {/* Navigation */}
      <nav className="w-full p-6 flex justify-between items-center max-w-7xl mx-auto relative z-10">
        <div className="flex items-center gap-2">
          <Wand2 className="text-pink-500" size={32} />
          <span className="font-fredoka text-3xl font-bold text-pink-600 tracking-wide">Cute DSL</span>
        </div>
        <div className="hidden md:flex gap-6 font-bold text-slate-700">
          <Link href="#models" className="hover:text-pink-500 transition-colors">Models</Link>
          <Link href="#training" className="hover:text-purple-500 transition-colors">LoRA</Link>
          <Link href="#api" className="hover:text-blue-500 transition-colors">API & Credits</Link>
          <Link href="#token" className="hover:text-cyan-500 transition-colors">$CUTE</Link>
          <Link href="#applied-science" className="hover:text-indigo-500 transition-colors">Applied Science</Link>
        </div>
        <div className="flex items-center gap-3">
          {walletAddress ? (
            <div className="flex items-center gap-3">
              <div className="hidden sm:flex items-center gap-2 bg-white/80 backdrop-blur-sm px-4 py-2 rounded-full border border-pink-200 shadow-sm">
                <Coins size={16} className="text-yellow-500" />
                <span className="font-bold text-slate-700">{balance ? formatCute(balance.credits) : '...'} $CUTE</span>
                {balance && cutePrice > 0 && (
                  <span className="text-xs text-slate-400">(${(balance.credits * cutePrice).toFixed(2)})</span>
                )}
              </div>
              <button
                onClick={disconnectWallet}
                className="flex items-center gap-2 bg-white/80 text-slate-600 font-bold px-4 py-2 rounded-full shadow-sm hover:shadow-md transition-all border border-slate-200 text-sm"
                title={walletAddress}
              >
                <Wallet size={16} />
                {walletAddress.slice(0, 4)}...{walletAddress.slice(-4)}
                <LogOut size={14} className="text-slate-400" />
              </button>
            </div>
          ) : (
            <button
              onClick={connectWallet}
              disabled={connectingWallet}
              className="bg-gradient-to-r from-pink-400 to-purple-400 text-white font-bold px-6 py-2 rounded-full shadow-lg hover:shadow-pink-300/50 hover:scale-105 transition-all flex items-center gap-2"
            >
              <Wallet size={18} />
              {connectingWallet ? 'Connecting...' : 'Connect Wallet'}
            </button>
          )}
        </div>
      </nav>

      {/* Hero Section */}
      <main className="max-w-7xl mx-auto px-6 pt-12 pb-24 relative z-10">
        <div className="flex flex-col lg:flex-row items-center gap-16">
          <motion.div 
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8 }}
            className="flex-1 text-center lg:text-left relative"
          >
            {/* Fairy Character Placeholder */}
            <div className="absolute -top-12 -left-12 animate-float hidden lg:block opacity-80">
              <Image src="https://picsum.photos/seed/fairy-char-1/150/150" alt="Fairy" width={100} height={100} className="rounded-full border-4 border-pink-200 shadow-lg" referrerPolicy="no-referrer" />
            </div>

            <div className="inline-flex items-center gap-2 bg-white/80 backdrop-blur-sm px-4 py-2 rounded-full text-pink-600 font-bold mb-6 border border-pink-200 shadow-sm">
              <Sparkles size={16} />
              <span>The most magical model conversion project</span>
            </div>
            <h1 className="font-fredoka text-6xl lg:text-8xl font-bold mb-6 leading-tight text-slate-800">
              Sprinkle <span className="text-gradient-fairy">Magic</span> on Your Models
            </h1>
            <p className="text-xl text-slate-700 mb-10 max-w-2xl mx-auto lg:mx-0 font-medium bg-white/40 p-4 rounded-2xl backdrop-blur-sm">
              Cute DSL is a fairy-themed AI model conversion project. We transform heavy models into lightweight, magical tools. Powered exclusively by $CUTE on Solana.
            </p>
            <div className="flex flex-col sm:flex-row gap-4 justify-center lg:justify-start">
              <a href="#models" className="bg-gradient-to-r from-pink-400 to-purple-400 text-white font-bold text-lg px-8 py-4 rounded-full shadow-lg hover:shadow-xl hover:scale-105 transition-all flex items-center justify-center gap-2">
                <Wand2 size={20} />
                Explore Models
              </a>
              <a href="#api" className="bg-white text-slate-700 font-bold text-lg px-8 py-4 rounded-full shadow-lg hover:shadow-xl hover:scale-105 transition-all flex items-center justify-center gap-2 border-2 border-pink-100">
                <Code size={20} className="text-blue-500" />
                API Docs
              </a>
            </div>
          </motion.div>
          
          <motion.div 
            initial={{ opacity: 0, scale: 0.8 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 0.8, delay: 0.2 }}
            className="flex-1 relative"
          >
            <div className="relative w-full max-w-lg mx-auto aspect-square animate-float">
              <div className="absolute inset-0 bg-gradient-to-tr from-pink-300 to-cyan-300 rounded-full blur-3xl opacity-50"></div>
              <Image 
                src="https://picsum.photos/seed/fairy-hero/800/800" 
                alt="Magical Fairy AI" 
                fill 
                className="object-cover rounded-full border-8 border-white/50 shadow-2xl"
                referrerPolicy="no-referrer"
              />
              {/* Floating badges */}
              <div className="absolute -top-6 -right-6 glass-card p-4 rounded-2xl flex items-center gap-3 animate-bounce" style={{ animationDuration: '3s' }}>
                <div className="bg-pink-100 p-2 rounded-full text-pink-500"><ImageIcon size={24} /></div>
                <div className="font-bold text-slate-700">zimage</div>
              </div>
              <div className="absolute -bottom-10 left-10 glass-card p-4 rounded-2xl flex items-center gap-3 animate-bounce" style={{ animationDuration: '4s', animationDelay: '1s' }}>
                <div className="bg-cyan-100 p-2 rounded-full text-cyan-500"><LineChart size={24} /></div>
                <div className="font-bold text-slate-700">chronos2</div>
              </div>
            </div>
          </motion.div>
        </div>
      </main>

      {/* Models Section */}
      <section id="models" className="py-24 relative z-10">
        <div className="absolute inset-0 bg-white/40 backdrop-blur-md -z-10"></div>
        <div className="max-w-7xl mx-auto px-6">
          <div className="text-center mb-16 relative">
            {/* Fairy Character Placeholder */}
            <div className="absolute -top-10 right-10 animate-float opacity-80 hidden md:block" style={{ animationDelay: '1s' }}>
              <Image src="https://picsum.photos/seed/fairy-char-2/120/120" alt="Fairy" width={80} height={80} className="rounded-full border-2 border-purple-200 shadow-md" referrerPolicy="no-referrer" />
            </div>
            <h2 className="font-fredoka text-4xl lg:text-5xl font-bold text-slate-800 mb-4">Our Magical Models</h2>
            <p className="text-lg text-slate-700 max-w-2xl mx-auto font-medium">Converted and optimized for maximum cuteness and performance.</p>
          </div>

          <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-6">
            <motion.div whileHover={{ y: -10 }} className="glass-card p-6 rounded-3xl relative overflow-hidden group bg-white/70">
              <div className="bg-pink-100 w-14 h-14 rounded-2xl flex items-center justify-center text-pink-500 mb-4 shadow-inner">
                <ImageIcon size={28} />
              </div>
              <h3 className="font-fredoka text-2xl font-bold text-slate-800 mb-2">zimage</h3>
              <p className="text-slate-600 mb-4 text-sm">
                Flagship image generation. Create stunning, fairy-themed artwork with just a few words.
              </p>
              <div className="flex items-center gap-2 text-pink-500 font-bold text-sm mt-auto">
                <Zap size={16} /> {getServicePrice('zimage') > 0 ? `${formatCute(getServicePrice('zimage'))} $CUTE` : '100 $CUTE'} / gen
              </div>
            </motion.div>

            <motion.div whileHover={{ y: -10 }} className="glass-card p-6 rounded-3xl relative overflow-hidden group bg-white/70">
              <div className="bg-cyan-100 w-14 h-14 rounded-2xl flex items-center justify-center text-cyan-500 mb-4 shadow-inner">
                <LineChart size={28} />
              </div>
              <h3 className="font-fredoka text-2xl font-bold text-slate-800 mb-2">chronos2</h3>
              <p className="text-slate-600 mb-4 text-sm">
                Time series forecasting, but make it cute. Predict future trends with high accuracy.
              </p>
              <div className="flex items-center gap-2 text-cyan-500 font-bold text-sm mt-auto">
                <Zap size={16} /> {getServicePrice('chronos2') > 0 ? `${formatCute(getServicePrice('chronos2'))} $CUTE` : '50 $CUTE'} / forecast
              </div>
            </motion.div>

            <motion.div whileHover={{ y: -10 }} className="glass-card p-6 rounded-3xl relative overflow-hidden group bg-white/70">
              <div className="bg-purple-100 w-14 h-14 rounded-2xl flex items-center justify-center text-purple-500 mb-4 shadow-inner">
                <Volume2 size={28} />
              </div>
              <h3 className="font-fredoka text-2xl font-bold text-slate-800 mb-2">Kokoro TTS</h3>
              <p className="text-slate-600 mb-4 text-sm">
                Magical Text-to-Speech. Give your applications a beautiful, enchanting voice.
              </p>
              <div className="flex items-center gap-2 text-purple-500 font-bold text-sm mt-auto">
                <Zap size={16} /> {getServicePrice('tts') > 0 ? `${formatCute(getServicePrice('tts'))} $CUTE` : '10 $CUTE'} / 100 chars
              </div>
            </motion.div>

            <motion.div whileHover={{ y: -10 }} className="glass-card p-6 rounded-3xl relative overflow-hidden group bg-white/70">
              <div className="bg-blue-100 w-14 h-14 rounded-2xl flex items-center justify-center text-blue-500 mb-4 shadow-inner">
                <Mic size={28} />
              </div>
              <h3 className="font-fredoka text-2xl font-bold text-slate-800 mb-2">Coherelabs STT</h3>
              <p className="text-slate-600 mb-4 text-sm">
                Speech-to-Text model. Understand every whisper and spell spoken by your users.
              </p>
              <div className="flex items-center gap-2 text-blue-500 font-bold text-sm mt-auto">
                <Zap size={16} /> {getServicePrice('stt') > 0 ? `${formatCute(getServicePrice('stt'))} $CUTE` : '20 $CUTE'} / minute
              </div>
            </motion.div>
          </div>
        </div>
      </section>

      {/* LoRA Training & Inference */}
      <section id="training" className="py-24 relative z-10">
        <div className="max-w-7xl mx-auto px-6">
          <div className="glass-card rounded-3xl p-10 lg:p-16 flex flex-col lg:flex-row items-center gap-12 bg-gradient-to-r from-purple-100/90 to-pink-100/90 backdrop-blur-xl">
            <div className="flex-1 relative">
              {/* Fairy Character Placeholder */}
              <div className="absolute -top-16 -left-8 animate-float opacity-90" style={{ animationDelay: '2s' }}>
                <Image src="https://picsum.photos/seed/fairy-char-3/100/100" alt="Fairy" width={80} height={80} className="rounded-full border-2 border-pink-300 shadow-md" referrerPolicy="no-referrer" />
              </div>

              <div className="bg-purple-200 w-16 h-16 rounded-2xl flex items-center justify-center text-purple-600 mb-6 shadow-inner">
                <Wand2 size={32} />
              </div>
              <h2 className="font-fredoka text-4xl lg:text-5xl font-bold text-slate-800 mb-6">LoRA Training & Inference</h2>
              <p className="text-lg text-slate-700 mb-6 font-medium">
                Want to add your own magical touch? We support full training and inference of custom LoRAs for both <strong className="text-pink-600">zimage</strong> and <strong className="text-cyan-600">chronos2</strong>.
              </p>
              <p className="text-md text-slate-600 mb-8">
                Upload your dataset, and our fairy workers will craft a personalized model just for you, ready to be queried via our API.
              </p>
              <ul className="space-y-4 mb-8">
                <li className="flex items-center gap-3 text-slate-700 font-medium">
                  <Star className="text-yellow-500" size={20} /> Fast training times on enchanted GPUs
                </li>
                <li className="flex items-center gap-3 text-slate-700 font-medium">
                  <Star className="text-yellow-500" size={20} /> LoRA support for Image Gen (zimage)
                </li>
                <li className="flex items-center gap-3 text-slate-700 font-medium">
                  <Star className="text-yellow-500" size={20} /> LoRA support for Time Series (chronos2)
                </li>
              </ul>
              <button className="bg-purple-500 text-white font-bold px-8 py-4 rounded-full shadow-lg hover:bg-purple-600 transition-colors">
                Start Training (5000 $CUTE)
              </button>
            </div>
            <div className="flex-1 relative w-full aspect-video rounded-2xl overflow-hidden shadow-2xl border-4 border-white/50">
              <Image 
                src="https://picsum.photos/seed/magic-lora/800/600" 
                alt="LoRA Training Magic" 
                fill 
                className="object-cover"
                referrerPolicy="no-referrer"
              />
            </div>
          </div>
        </div>
      </section>

      {/* API Usage & Cloud Credits */}
      <section id="api" className="py-24 relative z-10">
        <div className="absolute inset-0 bg-blue-50/60 backdrop-blur-md -z-10"></div>
        <div className="max-w-7xl mx-auto px-6">
          <div className="text-center mb-16">
            <h2 className="font-fredoka text-4xl lg:text-5xl font-bold text-slate-800 mb-4">Developer Magic</h2>
            <p className="text-lg text-slate-700 max-w-2xl mx-auto font-medium">Integrate our models into your own spells and applications.</p>
          </div>

          <div className="grid md:grid-cols-2 gap-8">
            <div className="glass-card p-10 rounded-3xl bg-white/80">
              <div className="flex items-center gap-4 mb-6">
                <div className="bg-blue-100 p-4 rounded-2xl text-blue-600"><BookOpen size={32} /></div>
                <h3 className="font-fredoka text-3xl font-bold text-slate-800">API Usage Docs</h3>
              </div>
              <p className="text-slate-600 mb-8 text-lg">
                Comprehensive documentation on how to authenticate, call our models (zimage, chronos2, Kokoro, Coherelabs), and manage your custom LoRAs.
              </p>
              <Link href="#docs" className="inline-flex items-center gap-2 text-blue-600 font-bold hover:text-blue-700">
                Read the Grimoire (Docs) &rarr;
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
                      {balance ? formatCute(balance.credits) : '...'} <span className="text-pink-500">$CUTE</span>
                    </div>
                    {balance && cutePrice > 0 && (
                      <div className="text-sm text-slate-400 mt-1">&asymp; ${(balance.credits * cutePrice).toFixed(2)} USD</div>
                    )}
                  </div>

                  {/* Deposit */}
                  <div>
                    <label className="text-sm font-bold text-slate-600 mb-2 block">Deposit $CUTE</label>
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
                      <div className="text-xs text-slate-400 mt-2">
                        &asymp; {formatCute(parseFloat(depositAmount || '0') / cutePrice)} $CUTE at current price (${cutePrice.toFixed(8)}/CUTE)
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
                              {event.amount >= 0 ? '+' : ''}{formatCute(Math.abs(event.amount))} $CUTE
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              ) : (
                <div className="text-center py-6">
                  <p className="text-slate-600 mb-6 text-lg">Connect your Solana wallet to deposit $CUTE and start using AI services.</p>
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

      {/* Tokenomics */}
      <section id="token" className="py-24 bg-slate-900 text-white relative z-10 overflow-hidden">
        <div className="absolute inset-0 bg-[url('https://picsum.photos/seed/stars/1920/1080')] opacity-20 mix-blend-overlay"></div>
        <div className="absolute top-0 left-0 w-full h-full bg-gradient-to-b from-transparent to-pink-900/80"></div>
        
        <div className="max-w-4xl mx-auto px-6 text-center relative z-10">
          <Coins size={64} className="text-yellow-400 mx-auto mb-8 animate-bounce" />
          <h2 className="font-fredoka text-5xl lg:text-6xl font-bold mb-6">Powered by $CUTE</h2>
          <p className="text-xl text-slate-200 mb-10 font-medium">
            Cute DSL operates exclusively on the Solana blockchain. The only way to pay for compute, model conversion, and inference is with our native memecoin, <span className="text-pink-400 font-bold text-2xl">$CUTE</span>.
          </p>
          
          <div className="bg-white/10 backdrop-blur-md border border-white/20 rounded-3xl p-8 mb-10">
            <div className="grid grid-cols-1 md:grid-cols-4 gap-8">
              <div>
                <div className="text-4xl font-bold text-pink-400 mb-2 font-fredoka">
                  {cutePrice > 0 ? `$${cutePrice < 0.01 ? cutePrice.toFixed(6) : cutePrice.toFixed(4)}` : '...'}
                </div>
                <div className="text-slate-300">$CUTE Price</div>
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
            href="https://bags.fm" 
            target="_blank" 
            rel="noopener noreferrer"
            className="inline-flex items-center gap-3 bg-gradient-to-r from-pink-500 to-purple-500 text-white font-bold text-xl px-10 py-5 rounded-full shadow-[0_0_30px_rgba(236,72,153,0.5)] hover:scale-105 transition-transform"
          >
            <Coins size={24} />
            Buy $CUTE on bags.fm
          </a>
        </div>
      </section>

      {/* Applied Science Company Section */}
      <section id="applied-science" className="py-24 relative z-10 bg-slate-50/90 backdrop-blur-lg border-t border-slate-200">
        <div className="max-w-7xl mx-auto px-6">
          <div className="text-center mb-16">
            <div className="inline-block bg-indigo-100 text-indigo-700 px-4 py-1 rounded-full font-bold text-sm mb-4">The Applied Science Company</div>
            <h2 className="font-fredoka text-4xl lg:text-5xl font-bold text-slate-800 mb-6">Our Ecosystem</h2>
            <p className="text-lg text-slate-600 max-w-3xl mx-auto">
              Cute DSL is part of a broader ecosystem of cutting-edge AI and technology products developed by the Applied Science Company.
            </p>
          </div>

          {/* Flagship Products */}
          <h3 className="text-2xl font-bold text-slate-800 mb-8 border-b border-slate-200 pb-2">Flagship Products</h3>
          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6 mb-16">
            <div className="bg-white p-6 rounded-2xl shadow-sm border border-slate-100 hover:shadow-md transition-shadow">
              <div className="flex justify-between items-start mb-4">
                <h4 className="font-bold text-xl text-slate-800">Dictatorflow.com</h4>
                <Mic className="text-indigo-500" size={20} />
              </div>
              <p className="text-slate-600 text-sm mb-4">Speak to your computer. Advanced voice control and dictation.</p>
            </div>
            
            <div className="bg-white p-6 rounded-2xl shadow-sm border border-slate-100 hover:shadow-md transition-shadow">
              <div className="flex justify-between items-start mb-4">
                <h4 className="font-bold text-xl text-slate-800">Netwrck.com</h4>
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
                <h4 className="font-bold text-xl text-slate-800">eBank.nz</h4>
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
                <h4 className="font-bold text-xl text-slate-800">Helix.app.nz</h4>
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
                <h4 className="font-bold text-xl text-slate-800">BitBank.nz</h4>
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
              <h4 className="font-bold text-lg text-slate-800 mb-2 flex items-center gap-2"><Code size={16}/> Text-Generator.io</h4>
              <p className="text-slate-600 text-sm">Secure, multilingual text and code generation powered by massive neural networks.</p>
            </div>
            <div className="bg-slate-100/50 p-6 rounded-2xl border border-slate-200">
              <h4 className="font-bold text-lg text-slate-800 mb-2 flex items-center gap-2"><Cpu size={16}/> StackHack</h4>
              <p className="text-slate-600 text-sm">Analyze and breakdown any technology stack instantly using Large Language Models.</p>
            </div>
            <div className="bg-slate-100/50 p-6 rounded-2xl border border-slate-200">
              <h4 className="font-bold text-lg text-slate-800 mb-2 flex items-center gap-2"><Layout size={16}/> WebSim</h4>
              <p className="text-slate-600 text-sm">Dream it, prompt it, browse it. Create entire simulated websites using LLMs on the fly.</p>
            </div>
          </div>

          {/* Legacy Portfolio */}
          <h3 className="text-2xl font-bold text-slate-800 mb-8 border-b border-slate-200 pb-2">Legacy Portfolio</h3>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
            <div className="bg-white p-4 rounded-xl text-center border border-slate-100 shadow-sm">
              <h4 className="font-bold text-slate-800 text-sm">How.nz</h4>
              <p className="text-xs text-slate-500 mt-1">Node deep dives</p>
            </div>
            <div className="bg-white p-4 rounded-xl text-center border border-slate-100 shadow-sm">
              <h4 className="font-bold text-slate-800 text-sm">Ring.nz</h4>
              <p className="text-xs text-slate-500 mt-1">Search Algorithms</p>
            </div>
            <div className="bg-white p-4 rounded-xl text-center border border-slate-100 shadow-sm">
              <h4 className="font-bold text-slate-800 text-sm">reWord Game</h4>
              <p className="text-xs text-slate-500 mt-1">Game Logic</p>
            </div>
            <div className="bg-white p-4 rounded-xl text-center border border-slate-100 shadow-sm">
              <h4 className="font-bold text-slate-800 text-sm">BigMultiplayerChess</h4>
              <p className="text-xs text-slate-500 mt-1">Real-time Sockets</p>
            </div>
            <div className="bg-white p-4 rounded-xl text-center border border-slate-100 shadow-sm">
              <h4 className="font-bold text-slate-800 text-sm">Evangeler.com</h4>
              <p className="text-xs text-slate-500 mt-1">Social Graph</p>
            </div>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="bg-white/90 backdrop-blur-md border-t border-pink-200 py-12 relative z-10">
        <div className="max-w-7xl mx-auto px-6">
          <div className="grid grid-cols-1 md:grid-cols-4 gap-8 mb-8">
            <div className="col-span-1 md:col-span-2">
              <div className="flex items-center gap-2 mb-4">
                <Wand2 className="text-pink-500" size={24} />
                <span className="font-fredoka text-2xl font-bold text-slate-800">Cute DSL</span>
              </div>
              <p className="text-slate-500 font-medium max-w-sm">
                A magical AI model conversion and training platform. Part of the Applied Science Company ecosystem.
              </p>
            </div>
            
            <div>
              <h4 className="font-bold text-slate-800 mb-4">Resources</h4>
              <ul className="space-y-2 text-slate-500 font-medium">
                <li><Link href="#models" className="hover:text-pink-500 transition-colors">Models (zimage, chronos2)</Link></li>
                <li><Link href="#training" className="hover:text-purple-500 transition-colors">LoRA Training & Inference</Link></li>
                <li><Link href="#api" className="hover:text-blue-500 transition-colors">API Usage Docs</Link></li>
                <li><Link href="#api" className="hover:text-yellow-500 transition-colors">Cloud Credits</Link></li>
              </ul>
            </div>

            <div>
              <h4 className="font-bold text-slate-800 mb-4">Ecosystem</h4>
              <ul className="space-y-2 text-slate-500 font-medium">
                <li><a href="https://netwrck.com" target="_blank" rel="noopener noreferrer" className="hover:text-indigo-500 transition-colors">Netwrck.com</a></li>
                <li><a href="https://ebank.nz" target="_blank" rel="noopener noreferrer" className="hover:text-indigo-500 transition-colors">eBank.nz</a></li>
                <li><a href="https://helix.app.nz" target="_blank" rel="noopener noreferrer" className="hover:text-indigo-500 transition-colors">Helix.app.nz</a></li>
                <li><a href="https://bitbank.nz" target="_blank" rel="noopener noreferrer" className="hover:text-indigo-500 transition-colors">BitBank.nz</a></li>
              </ul>
            </div>
          </div>
          
          <div className="border-t border-slate-200 pt-8 flex flex-col md:flex-row justify-between items-center gap-4">
            <p className="text-slate-400 font-medium text-sm">© 2026 Applied Science Company. All magic reserved.</p>
            <div className="flex gap-4">
              <a href="#" className="text-slate-400 hover:text-pink-500 transition-colors">Twitter</a>
              <a href="#" className="text-slate-400 hover:text-purple-500 transition-colors">Discord</a>
              <a href="#" className="text-slate-400 hover:text-cyan-500 transition-colors">GitHub</a>
            </div>
          </div>
        </div>
      </footer>
    </div>
  );
}
