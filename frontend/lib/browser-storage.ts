// Persistence is optional, and embedded browsers are hostile about it: the
// storage object itself can be absent or null (Dola/CEF WebViews, disabled
// cookies), the storage getter can throw, and individual methods can throw
// (Safari private mode, quota, enterprise policy). A missing store must never
// break a page or silently disable caller bookkeeping such as the frontend
// error reporter's per-session cap.
//
// Each store therefore keeps an in-memory mirror: values written during the
// page load are always readable again, even when the real store rejected them.
// Memory wins on read because it holds the newest write; the real store is only
// consulted for values from earlier page loads.
export interface BrowserStore {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

function createBrowserStore(readStore: () => Storage | null | undefined): BrowserStore {
  const memory = new Map<string, string>();
  let live: Storage | null | undefined;
  let resolved = false;

  const store = (): Storage | null => {
    if (!resolved) {
      resolved = true;
      try {
        live = readStore();
      } catch {
        live = null;
      }
    }
    return live || null;
  };

  return {
    getItem(key: string): string | null {
      const cached = memory.get(key);
      if (cached !== undefined) return cached;
      try {
        return store()?.getItem(key) ?? null;
      } catch {
        return null;
      }
    },
    setItem(key: string, value: string): void {
      memory.set(key, value);
      try {
        store()?.setItem(key, value);
      } catch {}
    },
    removeItem(key: string): void {
      memory.delete(key);
      try {
        store()?.removeItem(key);
      } catch {}
    },
  };
}

export const browserStorage = createBrowserStore(() => window.localStorage);
export const browserSessionStorage = createBrowserStore(() => window.sessionStorage);
