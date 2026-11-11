const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');
const source = ts.transpileModule(readFileSync(`${__dirname}/../../lib/browser-storage.ts`, 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS },
}).outputText;
function load(globals) {
  const context = { exports: {}, ...globals };
  vm.runInNewContext(source, context);
  return context.exports;
}

const brokenStores = [
  {},
  { window: { localStorage: null, sessionStorage: null } },
  { window: {} },
  { window: { get localStorage() { throw new Error('Storage denied'); }, get sessionStorage() { throw new Error('Storage denied'); } } },
];
const denied = () => { throw new Error('Storage denied'); };

test('SSR, null, undefined, denied getter and denied operations degrade safely', () => {
  for (const globals of [...brokenStores,
    { window: { localStorage: { getItem: denied, setItem: denied, removeItem: denied },
      sessionStorage: { getItem: denied, setItem: denied, removeItem: denied } } }]) {
    const { browserStorage, browserSessionStorage } = load(globals);
    for (const storage of [browserStorage, browserSessionStorage]) {
      assert.equal(storage.getItem('key'), null);
      assert.doesNotThrow(() => storage.setItem('key', 'value'));
      assert.doesNotThrow(() => storage.removeItem('key'));
    }
  }
});

test('writes rejected by a broken store stay readable in memory', () => {
  const values = new Map();
  const { browserStorage, browserSessionStorage } = load({ window: {
    localStorage: { getItem: key => values.get(key) ?? null, setItem: denied, removeItem: denied },
    sessionStorage: { getItem: denied, setItem: denied, removeItem: denied },
  } });
  // localStorage: reads work, writes and removals are denied.
  browserStorage.setItem('counter', '1');
  assert.equal(browserStorage.getItem('counter'), '1');
  browserStorage.removeItem('counter');
  assert.equal(browserStorage.getItem('counter'), null);
  // sessionStorage: every operation is denied, so the reporter's per-session
  // error count must still increment and stay removable.
  const sessionStorage = browserSessionStorage;
  sessionStorage.setItem('count', '1');
  sessionStorage.setItem('count', '2');
  assert.equal(sessionStorage.getItem('count'), '2');
  sessionStorage.removeItem('count');
  assert.equal(sessionStorage.getItem('count'), null);
});

test('normal persistence reads, overwrites and removes values', () => {
  const localValues = new Map();
  const sessionValues = new Map();
  const backend = values => ({
    getItem: key => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: key => values.delete(key),
  });
  const { browserStorage, browserSessionStorage } = load({ window: {
    localStorage: backend(localValues),
    sessionStorage: backend(sessionValues),
  } });
  for (const [storage, values] of [[browserStorage, localValues], [browserSessionStorage, sessionValues]]) {
    assert.equal(storage.getItem('key'), null);
    storage.setItem('key', 'one');
    assert.equal(storage.getItem('key'), 'one');
    storage.setItem('key', 'two');
    assert.equal(storage.getItem('key'), 'two');
    // Persisted writes reach the real store, so a later page load can read them.
    assert.equal(values.get('key'), 'two');
    storage.removeItem('key');
    assert.equal(storage.getItem('key'), null);
    assert.equal(values.has('key'), false);
  }
});

test('a persisted value from an earlier page load is read from the real store', () => {
  const { browserStorage } = load({ window: { localStorage: {
    getItem: () => 'stored-wallet',
    setItem: denied,
    removeItem: denied,
  } } });
  assert.equal(browserStorage.getItem('cutedsl_wallet'), 'stored-wallet');
});

test('quota failure does not prevent reading or removing existing values', () => {
  const values = new Map([['key', 'existing']]);
  const { browserStorage } = load({ window: { localStorage: {
    getItem: key => values.get(key) ?? null,
    setItem() { throw new Error('QuotaExceededError'); },
    removeItem: key => values.delete(key),
  } } });
  browserStorage.setItem('key', 'replacement');
  assert.equal(browserStorage.getItem('key'), 'replacement');
  assert.equal(values.get('key'), 'existing');
  browserStorage.removeItem('key');
  assert.equal(browserStorage.getItem('key'), null);
  assert.equal(values.has('key'), false);
});
