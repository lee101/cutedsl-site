#!/usr/bin/env node
// Production browser/asset check for CuteDSL. Always emits one JSON document;
// callers inspect `ok` instead of relying on process exit status.

import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(here, '..');
const requireFromFrontend = createRequire(resolve(repo, 'frontend/package.json'));
const { chromium } = requireFromFrontend('playwright');

const args = process.argv.slice(2);
const targetArg = args.indexOf('--targets');
const targetsFile = targetArg >= 0 && args[targetArg + 1]
  ? resolve(args[targetArg + 1])
  : resolve(here, 'frontend_targets.json');
const targets = JSON.parse(readFileSync(targetsFile, 'utf8'));

const ignored = [
  /ERR_ABORTED/i,
  /ERR_BLOCKED_BY_CLIENT/i,
  /ResizeObserver loop/i,
  /favicon\.ico/i,
  /google-analytics|googletagmanager|doubleclick/i,
  /Unable to download payment manifest/i,
];

const firstParty = (url) => {
  try {
    const host = new URL(url).hostname;
    return host === 'cutedsl.cc' || host === 'www.cutedsl.cc' || host === 'appstatic.app.nz';
  } catch {
    return false;
  }
};
const shouldIgnore = (text) => ignored.some((pattern) => pattern.test(text));

async function scan(browser, base, target) {
  const viewport = target.viewport || { width: 1365, height: 900 };
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  const errors = [];

  const add = (kind, message, extra = {}) => {
    if (!shouldIgnore(message)) errors.push({ kind, message, ...extra });
  };
  page.on('pageerror', (error) => add('pageerror', error.message, { stack: error.stack || '' }));
  page.on('console', (message) => {
    if (message.type() === 'error') add('console.error', message.text());
  });
  page.on('requestfailed', (request) => {
    if (!firstParty(request.url())) return;
    add('requestfailed', `${request.url()} ${request.failure()?.errorText || ''}`, { url: request.url() });
  });
  page.on('response', (response) => {
    if (!firstParty(response.url())) return;
    const status = response.status();
    const isAsset = response.url().includes('/cutedsl/static/');
    if (status >= 500 || (isAsset && status >= 400)) {
      add('http', `HTTP ${status} ${response.url()}`, { url: response.url(), status });
    }
  });

  let status = 0;
  let title = '';
  let navigationError = '';
  let applicationError = false;
  const started = Date.now();
  try {
    const separator = target.path.includes('?') ? '&' : '?';
    const url = `${base.replace(/\/$/, '')}${target.path}${separator}monitor_check=${Date.now()}`;
    const response = await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 45_000 });
    status = response?.status() || 0;
    if (status !== 200) add('navigation_http', `HTTP ${status || 'no response'} ${url}`, { status, url });
    await page.waitForLoadState('networkidle', { timeout: 12_000 }).catch(() => {});
    await page.waitForTimeout(target.settleMs || 1500);
    title = await page.title();
    const body = await page.locator('body').innerText().catch(() => '');
    applicationError = /Application error:\s*a client-side exception/i.test(body);
    if (applicationError) add('application_error', 'Next.js client-side exception page rendered');
    if (!title.trim()) add('empty_title', 'Document title is empty after hydration');
  } catch (error) {
    navigationError = error instanceof Error ? error.message : String(error);
    add('navigation', navigationError);
  } finally {
    await context.close();
  }

  return {
    path: target.path,
    viewport,
    status,
    title,
    applicationError,
    navigationError,
    durationMs: Date.now() - started,
    errors,
    ok: status === 200 && Boolean(title.trim()) && !applicationError && errors.length === 0,
  };
}

let browser;
try {
  browser = await chromium.launch({ headless: true });
  const scans = [];
  for (const site of targets.sites) {
    for (const target of site.routes) scans.push(await scan(browser, site.base, target));
  }
  const ok = scans.every((scan) => scan.ok);
  console.log(JSON.stringify({ checkedAt: new Date().toISOString(), ok, scans }, null, 2));
} catch (error) {
  console.log(JSON.stringify({
    checkedAt: new Date().toISOString(),
    ok: false,
    scannerError: error instanceof Error ? error.stack || error.message : String(error),
    scans: [],
  }, null, 2));
} finally {
  if (browser) await browser.close();
}
