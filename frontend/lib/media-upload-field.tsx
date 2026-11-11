'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { Upload, Mic, Square, Loader2, X, Link as LinkIcon, Sparkles } from 'lucide-react';
import { uploadToBucket, extensionForMime } from '@/lib/uploads';
import { pickRecorderMimeType, toMonoWav } from '@/lib/audio-wav';

export type UploadKind = 'audio' | 'image' | 'video' | 'file';

export interface UploadExample {
  label: string;
  url: string;
}

const ACCEPT: Record<UploadKind, string> = {
  audio: 'audio/*',
  image: 'image/*',
  video: 'video/*',
  file: '*/*',
};

const KIND_LABEL: Record<UploadKind, string> = {
  audio: 'audio file',
  image: 'image',
  video: 'video',
  file: 'file',
};

function formatSeconds(total: number) {
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${String(s).padStart(2, '0')}`;
}

export function MediaUploadField({
  kind,
  value,
  onChange,
  apiKey,
  dataset = 'uploads',
  examples = [],
  placeholder,
}: {
  kind: UploadKind;
  value: string;
  onChange: (url: string) => void;
  apiKey: string | null;
  dataset?: string;
  examples?: UploadExample[];
  placeholder?: string;
}) {
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [recording, setRecording] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopTimer = () => {
    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = null;
  };

  useEffect(() => () => {
    stopTimer();
    recorderRef.current?.stream.getTracks().forEach(t => t.stop());
  }, []);

  const upload = useCallback(
    async (blob: Blob, filename: string) => {
      setError(null);
      setUploading(true);
      setProgress(0);
      try {
        const url = await uploadToBucket(blob, {
          apiKey,
          dataset,
          filename,
          contentType: blob.type || undefined,
          onProgress: setProgress,
        });
        onChange(url);
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Upload failed');
      } finally {
        setUploading(false);
      }
    },
    [apiKey, dataset, onChange],
  );

  const handleFiles = useCallback(
    (files: FileList | null) => {
      const file = files?.[0];
      if (!file) return;
      void upload(file, file.name);
    },
    [upload],
  );

  const startRecording = async () => {
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeType = pickRecorderMimeType();
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      chunksRef.current = [];
      recorder.ondataavailable = e => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };
      recorder.onstop = async () => {
        stopTimer();
        stream.getTracks().forEach(t => t.stop());
        setRecording(false);
        const raw = new Blob(chunksRef.current, { type: recorder.mimeType || 'audio/webm' });
        if (raw.size === 0) {
          setError('Nothing was recorded — check your microphone.');
          return;
        }
        const wav = await toMonoWav(raw);
        const ext = extensionForMime(wav.type || 'audio/wav');
        await upload(wav, `recording.${ext}`);
      };
      recorderRef.current = recorder;
      recorder.start();
      setRecording(true);
      setElapsed(0);
      timerRef.current = setInterval(() => setElapsed(s => s + 1), 1000);
    } catch (e) {
      setError(
        e instanceof Error && e.name === 'NotAllowedError'
          ? 'Microphone permission denied.'
          : 'Could not start recording on this device.',
      );
    }
  };

  const stopRecording = () => recorderRef.current?.stop();

  return (
    <div className="space-y-2" data-testid={`upload-field-${kind}`}>
      <div
        onDragOver={e => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={e => {
          e.preventDefault();
          setDragging(false);
          handleFiles(e.dataTransfer.files);
        }}
        className={`rounded-xl border-2 border-dashed px-4 py-5 text-center transition-colors ${
          dragging ? 'border-pink-400 bg-pink-50' : 'border-slate-200 bg-slate-50/60'
        }`}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept={ACCEPT[kind]}
          className="hidden"
          data-testid={`upload-input-${kind}`}
          onChange={e => {
            handleFiles(e.target.files);
            e.target.value = '';
          }}
        />

        {recording ? (
          <div className="flex flex-col items-center gap-2">
            <div className="flex items-center gap-2 text-sm font-bold text-red-500">
              <span className="w-2.5 h-2.5 rounded-full bg-red-500 animate-pulse" />
              Recording {formatSeconds(elapsed)}
            </div>
            <button
              type="button"
              onClick={stopRecording}
              data-testid="stop-recording"
              className="inline-flex items-center gap-2 bg-red-500 text-white text-sm font-bold px-4 py-2 rounded-lg hover:bg-red-600 transition-colors"
            >
              <Square size={14} /> Stop &amp; upload
            </button>
          </div>
        ) : uploading ? (
          <div className="flex flex-col items-center gap-2">
            <div className="flex items-center gap-2 text-sm font-bold text-slate-600">
              <Loader2 size={16} className="animate-spin text-pink-500" /> Uploading… {progress}%
            </div>
            <div className="w-full max-w-xs h-1.5 bg-slate-200 rounded-full overflow-hidden">
              <div className="h-full bg-gradient-to-r from-pink-400 to-purple-400 transition-all" style={{ width: `${progress}%` }} />
            </div>
          </div>
        ) : (
          <div className="flex flex-col items-center gap-2">
            <p className="text-sm text-slate-500">
              Drop {KIND_LABEL[kind]} here, or
            </p>
            <div className="flex flex-wrap items-center justify-center gap-2">
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                data-testid={`browse-${kind}`}
                className="inline-flex items-center gap-2 bg-white border border-slate-200 text-slate-700 text-sm font-bold px-4 py-2 rounded-lg hover:border-pink-300 hover:text-pink-600 transition-colors"
              >
                <Upload size={14} /> Choose file
              </button>
              {kind === 'audio' && (
                <button
                  type="button"
                  onClick={startRecording}
                  data-testid="record-audio"
                  className="inline-flex items-center gap-2 bg-gradient-to-r from-pink-400 to-purple-400 text-white text-sm font-bold px-4 py-2 rounded-lg hover:shadow-md transition-all"
                >
                  <Mic size={14} /> Record from mic
                </button>
              )}
            </div>
            <p className="text-xs text-slate-400">Uploaded straight to CuteDSL storage — up to 100 MB.</p>
          </div>
        )}
      </div>

      {examples.length > 0 && !recording && !uploading && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-slate-400 flex items-center gap-1"><Sparkles size={12} /> Examples:</span>
          {examples.map(ex => (
            <button
              key={ex.url}
              type="button"
              onClick={() => onChange(ex.url)}
              data-testid="use-example"
              className="text-xs font-bold text-pink-600 bg-pink-50 border border-pink-200 px-2.5 py-1 rounded-full hover:bg-pink-100 transition-colors"
            >
              {ex.label}
            </button>
          ))}
        </div>
      )}

      <div className="flex items-center gap-2">
        <LinkIcon size={14} className="text-slate-300 shrink-0" />
        <input
          type="text"
          value={value}
          onChange={e => onChange(e.target.value)}
          placeholder={placeholder || `https://… ${KIND_LABEL[kind]} URL`}
          className="w-full bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-pink-300"
        />
        {value && (
          <button
            type="button"
            onClick={() => onChange('')}
            aria-label="Clear"
            className="text-slate-400 hover:text-red-500 transition-colors shrink-0"
          >
            <X size={16} />
          </button>
        )}
      </div>

      {error && <p className="text-xs text-red-600">{error}</p>}

      {value && !uploading && (
        <div className="pt-1">
          {kind === 'audio' && <audio controls src={value} className="w-full" data-testid="upload-preview-audio" />}
          {kind === 'image' && (
            /* eslint-disable-next-line @next/next/no-img-element */
            <img src={value} alt="Upload preview" className="max-h-48 rounded-lg border border-slate-200" data-testid="upload-preview-image" />
          )}
          {kind === 'video' && <video controls src={value} className="max-h-48 rounded-lg border border-slate-200" data-testid="upload-preview-video" />}
        </div>
      )}
    </div>
  );
}

export default MediaUploadField;
