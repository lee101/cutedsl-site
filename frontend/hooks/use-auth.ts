'use client';

import { useState, useEffect } from 'react';

interface AuthState {
  walletAddress: string | null;
  apiKey: string | null;
  email: string | null;
  isLoggedIn: boolean;
}

export function useAuth(): AuthState {
  const [walletAddress, setWalletAddress] = useState<string | null>(null);
  const [apiKey, setApiKey] = useState<string | null>(null);
  const [email, setEmail] = useState<string | null>(null);

  useEffect(() => {
    const saved = localStorage.getItem('cutedsl_wallet');
    if (saved) setWalletAddress(saved);
    const savedKey = localStorage.getItem('cutedsl_api_key');
    if (savedKey) setApiKey(savedKey);
    const savedEmail = localStorage.getItem('cutedsl_email');
    if (savedEmail) setEmail(savedEmail);
  }, []);

  return { walletAddress, apiKey, email, isLoggedIn: !!apiKey };
}

export function replaceApiKey(template: string, apiKey: string | null): string {
  if (!apiKey) return template;
  return template.replace(/YOUR_API_KEY/g, apiKey);
}
