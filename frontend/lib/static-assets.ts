const DEFAULT_STATIC_BASE_URL = '';

export const STATIC_BASE_URL = (
  process.env.NEXT_PUBLIC_STATIC_BASE_URL || DEFAULT_STATIC_BASE_URL
).replace(/\/$/, '');

export function staticAssetPath(path: string) {
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;
  return `${STATIC_BASE_URL}${normalizedPath}`;
}
