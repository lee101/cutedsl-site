'use client';

import { useEffect } from 'react';
import { browserSessionStorage } from '@/lib/browser-storage';

function endpoint() {
  if (location.hostname === 'appstatic.app.nz') {
    return 'https://cutedsl.cc/api/frontend-error';
  }
  return '/api/frontend-error';
}
const SESSION_KEY = 'cutedsl_frontend_error_session';
const COUNT_KEY = 'cutedsl_frontend_error_count';
const MAX_PER_SESSION = 20;
const CEF_SHARP_OBJECT_NOT_FOUND_RE =
  /^Object Not Found Matching Id:\d+,\s*MethodName:(?:update,\s*ParamCount:4|simulateEvent,\s*ParamCount:\d+)$/;
// Browsers replace the message of a cross-origin script failure with this
// opaque string and drop source, stack, and position. Our own bundles are
// served from a CDN with `Access-Control-Allow-Origin` and loaded with
// `crossorigin`, so a masked event can only come from a script we do not
// control (extension, injected ad, embedded host) and carries nothing to act
// on. Re-verify that policy before widening this filter.
const OPAQUE_SCRIPT_ERROR = 'Script error.';

function getSessionId() {
  const existing = browserSessionStorage.getItem(SESSION_KEY);
  if (existing) return existing;
  let id: string;
  try {
    id = crypto.randomUUID();
  } catch {
    // randomUUID is missing outside secure contexts.
    id = `s-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
  }
  browserSessionStorage.setItem(SESSION_KEY, id);
  return id;
}

function safeString(value: unknown, fallback = '') {
  if (typeof value === 'string') return value;
  if (value instanceof Error) return value.message;
  try {
    const serialized = JSON.stringify(value);
    return typeof serialized === 'string' ? serialized : fallback;
  } catch {
    return fallback;
  }
}

function shouldIgnoreBrowserNoise(message: string) {
  return CEF_SHARP_OBJECT_NOT_FOUND_RE.test(message.trim());
}

function isOpaqueScriptError(event: ErrorEvent) {
  return (
    event.message.trim() === OPAQUE_SCRIPT_ERROR &&
    !event.filename &&
    !event.lineno &&
    !event.colno &&
    !event.error
  );
}

// Every context field below is read while handling an error, so a throwing
// accessor must degrade to an empty value instead of raising a second error.
function contextValue(read: () => string): string {
  try {
    return read();
  } catch {
    return '';
  }
}

function connectionInfo() {
  try {
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
  } catch {
    return undefined;
  }
}

function sendFrontendError(payload: Record<string, unknown>) {
  try {
    const count = Number.parseInt(browserSessionStorage.getItem(COUNT_KEY) || '0', 10) || 0;
    if (count >= MAX_PER_SESSION) return;
    browserSessionStorage.setItem(COUNT_KEY, String(count + 1));
  } catch {
    // Counting is best-effort; never let bookkeeping drop the report itself.
  }

  const body = JSON.stringify({
    level: 'error',
    url: location.href,
    referrer: document.referrer,
    userAgent: navigator.userAgent,
    language: navigator.language,
    timezone: contextValue(() => Intl.DateTimeFormat().resolvedOptions().timeZone || ''),
    viewport: { width: window.innerWidth, height: window.innerHeight },
    screen: { width: window.screen.width, height: window.screen.height },
    connection: connectionInfo(),
    appVersion: process.env.NEXT_PUBLIC_APP_VERSION || '',
    buildId: process.env.NEXT_PUBLIC_BUILD_ID || '',
    occurredAt: new Date().toISOString(),
    sessionId: getSessionId(),
    ...payload,
  });

  try {
    if (navigator.sendBeacon) {
      const blob = new Blob([body], { type: 'application/json' });
      if (navigator.sendBeacon(endpoint(), blob)) return;
    }
  } catch {
    // Restricted browser environments can expose sendBeacon but throw on use.
    // Fall back to fetch without creating a second uncaught reporter error.
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
      if (shouldIgnoreBrowserNoise(event.message) || isOpaqueScriptError(event)) return;
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
      const message = safeString(reason, 'Unhandled promise rejection');
      if (shouldIgnoreBrowserNoise(message)) return;
      sendFrontendError({
        message,
        name: reason instanceof Error ? reason.name : 'UnhandledPromiseRejection',
        stack: reason instanceof Error ? reason.stack || '' : '',
        source: 'unhandledrejection',
        fingerprint: `unhandledrejection|${message.slice(0, 240)}`,
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
