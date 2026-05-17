'use client';

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
    const walletAddress = localStorage.getItem('cutedsl_wallet');
    const apiKey = localStorage.getItem('cutedsl_api_key');
    const email = localStorage.getItem('cutedsl_email');

    queueMicrotask(() => {
      setAuth({
        walletAddress,
        apiKey,
        email,
        isLoggedIn: !!apiKey,
      });
    });
  }, []);

  return auth;
}

export function replaceApiKey(template: string, apiKey: string | null): string {
  if (!apiKey) return template;
  return template.replace(/YOUR_API_KEY/g, apiKey);
}
