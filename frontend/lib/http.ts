export class HTTPResponseError extends Error {
  status: number;
  statusText: string;
  data: unknown;

  constructor(message: string, res: Response, data: unknown) {
    super(message);
    this.name = 'HTTPResponseError';
    this.status = res.status;
    this.statusText = res.statusText;
    this.data = data;
  }
}

function messageFromData(data: unknown): string | null {
  if (!data || typeof data !== 'object') return null;
  const record = data as Record<string, unknown>;
  if (typeof record.error === 'string' && record.error.trim()) return record.error;
  if (typeof record.message === 'string' && record.message.trim()) return record.message;
  return null;
}

function textFallback(text: string): string | null {
  const trimmed = text.trim();
  const lower = trimmed.toLowerCase();
  if (!trimmed || lower.startsWith('<!doctype') || lower.startsWith('<html')) return null;
  return trimmed.slice(0, 200);
}

export async function parseJSONResponse<T>(res: Response, fallback: string): Promise<T> {
  const contentType = res.headers.get('content-type') || '';
  const text = await res.text();
  let data: unknown = {};

  if (text.trim()) {
    try {
      data = JSON.parse(text);
    } catch {
      data = {};
    }
  }

  if (!res.ok) {
    const message =
      messageFromData(data) ||
      textFallback(text) ||
      `${fallback} (${res.status}${res.statusText ? ` ${res.statusText}` : ''})`;
    throw new HTTPResponseError(message, res, data);
  }

  const parsedEmptyObject =
    data !== null &&
    typeof data === 'object' &&
    !Array.isArray(data) &&
    Object.keys(data).length === 0;
  if (!contentType.includes('application/json') && text.trim() && parsedEmptyObject) {
    throw new Error(`${fallback}: expected JSON response`);
  }

  return data as T;
}
