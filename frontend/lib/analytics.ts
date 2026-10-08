type Props = Record<string, unknown>;
type Th = (...args: unknown[]) => void;
export type AuthMethod = 'email' | 'wallet';

function th(): Th | undefined {
  return typeof window === 'undefined' ? undefined : (window as unknown as { th?: Th }).th;
}

export function track(event: string, props?: Props) {
  try { th()?.('track', event, props); } catch {}
}

export function identify(userId?: string | null) {
  if (userId) try { th()?.('identify', userId); } catch {}
}

export function trackAuthStarted(method: AuthMethod, surface: string) {
  track('sign_in_started', { method, surface });
}

export function trackAuthCompleted(method: AuthMethod, surface: string, data: { created?: boolean; user?: object }) {
  const id = (data.user as { id?: unknown } | undefined)?.id;
  identify(typeof id === 'string' ? id : undefined);
  track(data.created ? 'sign_up_completed' : 'sign_in_completed', { method, surface });
}

export function analyticsIds(surface: string) {
  const ids: Props = { th_surface: surface };
  try {
    ids.th_cid = window.localStorage.getItem('th_cid') || undefined;
    ids.th_sid = window.localStorage.getItem('th_sid') || undefined;
  } catch {}
  return ids;
}
