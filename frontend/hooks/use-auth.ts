'use client';

import { browserStorage } from '@/lib/browser-storage';

import { useState, useEffect } from 'react';

interface AuthState {
  walletAddress: string | null;
  apiKey: string | null;
  email: string | null;
  isLoggedIn: boolean;
}

export function useAuth(): AuthState {
  const [auth, setAuth] = useState<AuthState>({
    walletAddress: null,
    apiKey: null,
    email: null,
    isLoggedIn: false,
  });

  useEffect(() => {
    const walletAddress = browserStorage.getItem('cutedsl_wallet');
    const apiKey = browserStorage.getItem('cutedsl_api_key');
    const email = browserStorage.getItem('cutedsl_email');

    queueMicrotask(() => {
      setAuth({
        walletAddress,
        apiKey,
        email,
        isLoggedIn: !!apiKey,
      });
    });

    // A key that no longer resolves to an account leaves every page looking
    // signed in while requests fail with "invalid API key". Only a 401 clears
    // it — network errors must not sign the user out.
    if (!apiKey) return;
    fetch('/api/auth/session', { headers: { Authorization: `Bearer ${apiKey}` } })
      .then((res) => {
        if (res.status !== 401) return;
        browserStorage.removeItem('cutedsl_api_key');
        browserStorage.removeItem('cutedsl_wallet');
        browserStorage.removeItem('cutedsl_email');
        setAuth({ walletAddress: null, apiKey: null, email: null, isLoggedIn: false });
      })
      .catch(() => {});
  }, []);

  return auth;
}

export function maskApiKey(apiKey: string | null): string {
  if (!apiKey) return '';
  if (apiKey.length <= 12) return '••••••••••••••••••••';
  return `${apiKey.slice(0, 8)}${'•'.repeat(20)}`;
}

export function replaceApiKey(template: string, apiKey: string | null, reveal = false): string {
  if (!apiKey || !reveal) return template;
  return template.replace(/YOUR_API_KEY/g, apiKey);
}
