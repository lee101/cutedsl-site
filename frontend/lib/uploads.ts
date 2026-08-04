import { parseJSONResponse } from '@/lib/http';

const API_BASE = '/api';

export interface PresignedTarget {
  upload_url: string;
  public_url: string;
  object_key: string;
  content_type: string;
  expires_in: number;
}

export interface UploadOptions {
  apiKey: string | null;
  dataset?: string;
  filename?: string;
  contentType?: string;
  onProgress?: (percent: number) => void;
  signal?: AbortSignal;
}

export const MAX_UPLOAD_BYTES = 100 * 1024 * 1024;

export function extensionForMime(mime: string): string {
  const map: Record<string, string> = {
    'audio/webm': 'webm',
    'audio/ogg': 'ogg',
    'audio/mpeg': 'mp3',
    'audio/mp4': 'm4a',
    'audio/wav': 'wav',
    'audio/x-wav': 'wav',
    'video/mp4': 'mp4',
    'video/webm': 'webm',
    'image/webp': 'webp',
    'image/png': 'png',
    'image/jpeg': 'jpg',
  };
  return map[mime.split(';')[0]] || 'bin';
}

async function presignUpload(
  filename: string,
  contentType: string,
  dataset: string,
  apiKey: string,
): Promise<PresignedTarget> {
  const params = new URLSearchParams({ filename, content_type: contentType, dataset });
  const res = await fetch(`${API_BASE}/uploads/presign?${params}`, {
    headers: { Authorization: `Bearer ${apiKey}` },
  });
  return parseJSONResponse<PresignedTarget>(res, `Could not prepare upload (${res.status})`);
}

/**
 * Upload a File/Blob straight to CuteDSL object storage via a presigned PUT and
 * return the public URL the AI services can fetch.
 */
export async function uploadToBucket(file: Blob, opts: UploadOptions): Promise<string> {
  const { apiKey, onProgress, signal } = opts;
  if (!apiKey) throw new Error('Sign in to upload files.');
  if (file.size === 0) throw new Error('File is empty.');
  if (file.size > MAX_UPLOAD_BYTES) {
    throw new Error(`File is too large (max ${Math.round(MAX_UPLOAD_BYTES / 1024 / 1024)} MB).`);
  }

  const named = file as File;
  const contentType = opts.contentType || named.type || 'application/octet-stream';
  const filename = opts.filename || named.name || `upload.${extensionForMime(contentType)}`;
  const dataset = opts.dataset || 'uploads';

  const target = await presignUpload(filename, contentType, dataset, apiKey);

  await new Promise<void>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('PUT', target.upload_url);
    xhr.setRequestHeader('Content-Type', contentType);
    xhr.upload.addEventListener('progress', e => {
      if (e.lengthComputable && onProgress) onProgress(Math.round((e.loaded / e.total) * 100));
    });
    xhr.onload = () =>
      xhr.status >= 200 && xhr.status < 300
        ? resolve()
        : reject(new Error(`Upload failed (${xhr.status})`));
    xhr.onerror = () => reject(new Error('Network error during upload'));
    xhr.onabort = () => reject(new Error('Upload cancelled'));
    if (signal) {
      if (signal.aborted) {
        xhr.abort();
      } else {
        signal.addEventListener('abort', () => xhr.abort(), { once: true });
      }
    }
    xhr.send(file);
  });

  onProgress?.(100);
  return target.public_url;
}
