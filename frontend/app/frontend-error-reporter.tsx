'use client';

import { useEffect } from 'react';

function endpoint() {
  if (location.hostname === 'appstatic.app.nz') {
    return 'https://cutedsl.cc/api/frontend-error';
  }
  return '/api/frontend-error';
}
const SESSION_KEY = 'cutedsl_frontend_error_session';
const MAX_PER_SESSION = 20;

function getSessionId() {
  try {
    let id = sessionStorage.getItem(SESSION_KEY);
    if (!id) {
      id = crypto.randomUUID();
      sessionStorage.setItem(SESSION_KEY, id);
    }
    return id;
  } catch {
    return '';
  }
}

function safeString(value: unknown, fallback = '') {
  if (typeof value === 'string') return value;
  if (value instanceof Error) return value.message;
  try {
    return JSON.stringify(value);
  } catch {
    return fallback;
  }
}

function connectionInfo() {
  const nav = navigator as Navigator & {
    connection?: {
      effectiveType?: string;
      downlink?: number;
      rtt?: number;
      saveData?: boolean;
    };
  };
  if (!nav.connection) return undefined;
  return {
    effectiveType: nav.connection.effectiveType,
    downlink: nav.connection.downlink,
    rtt: nav.connection.rtt,
    saveData: nav.connection.saveData,
  };
}

function sendFrontendError(payload: Record<string, unknown>) {
  try {
    const count = Number(sessionStorage.getItem('cutedsl_frontend_error_count') || '0');
    if (count >= MAX_PER_SESSION) return;
    sessionStorage.setItem('cutedsl_frontend_error_count', String(count + 1));
  } catch {}

  const body = JSON.stringify({
    level: 'error',
    url: location.href,
    referrer: document.referrer,
    userAgent: navigator.userAgent,
    language: navigator.language,
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    viewport: { width: window.innerWidth, height: window.innerHeight },
    screen: { width: window.screen.width, height: window.screen.height },
    connection: connectionInfo(),
    appVersion: process.env.NEXT_PUBLIC_APP_VERSION || '',
    buildId: process.env.NEXT_PUBLIC_BUILD_ID || '',
    occurredAt: new Date().toISOString(),
    sessionId: getSessionId(),
    ...payload,
  });

  if (navigator.sendBeacon) {
    const blob = new Blob([body], { type: 'application/json' });
    if (navigator.sendBeacon(endpoint(), blob)) return;
  }

  fetch(endpoint(), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body,
    keepalive: true,
  }).catch(() => {});
}

export function FrontendErrorReporter() {
  useEffect(() => {
    const onError = (event: ErrorEvent) => {
      sendFrontendError({
        message: event.message,
        name: event.error?.name || 'Error',
        stack: event.error?.stack || '',
        source: event.filename,
        lineno: event.lineno,
        colno: event.colno,
        fingerprint: `${event.message}|${event.filename}|${event.lineno}|${event.colno}`,
      });
    };

    const onUnhandledRejection = (event: PromiseRejectionEvent) => {
      const reason = event.reason;
      sendFrontendError({
        message: safeString(reason, 'Unhandled promise rejection'),
        name: reason instanceof Error ? reason.name : 'UnhandledPromiseRejection',
        stack: reason instanceof Error ? reason.stack || '' : '',
        source: 'unhandledrejection',
        fingerprint: `unhandledrejection|${safeString(reason).slice(0, 240)}`,
      });
    };

    window.addEventListener('error', onError);
    window.addEventListener('unhandledrejection', onUnhandledRejection);
    return () => {
      window.removeEventListener('error', onError);
      window.removeEventListener('unhandledrejection', onUnhandledRejection);
    };
  }, []);

  return null;
}
