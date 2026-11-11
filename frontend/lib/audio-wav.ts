const TARGET_SAMPLE_RATE = 16000;

function encodeWAV(samples: Float32Array, sampleRate: number): Blob {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const writeString = (offset: number, s: string) => {
    for (let i = 0; i < s.length; i++) view.setUint8(offset + i, s.charCodeAt(i));
  };

  writeString(0, 'RIFF');
  view.setUint32(4, 36 + samples.length * 2, true);
  writeString(8, 'WAVE');
  writeString(12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, 1, true); // mono
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeString(36, 'data');
  view.setUint32(40, samples.length * 2, true);

  let offset = 44;
  for (let i = 0; i < samples.length; i++) {
    const clamped = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(offset, clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff, true);
    offset += 2;
  }
  return new Blob([buffer], { type: 'audio/wav' });
}

/**
 * Convert a recorded blob (webm/opus, mp4, …) to mono 16 kHz PCM WAV so every
 * transcription backend can read it. Returns the original blob if the browser
 * cannot decode it.
 */
export async function toMonoWav(blob: Blob): Promise<Blob> {
  try {
    const arrayBuffer = await blob.arrayBuffer();
    const Ctx: typeof AudioContext =
      window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    const decodeCtx = new Ctx();
    const decoded = await decodeCtx.decodeAudioData(arrayBuffer.slice(0));
    await decodeCtx.close();

    const frames = Math.max(1, Math.ceil((decoded.duration || 0) * TARGET_SAMPLE_RATE));
    const offline = new OfflineAudioContext(1, frames, TARGET_SAMPLE_RATE);
    const source = offline.createBufferSource();
    source.buffer = decoded;
    source.connect(offline.destination);
    source.start();
    const rendered = await offline.startRendering();
    return encodeWAV(rendered.getChannelData(0), TARGET_SAMPLE_RATE);
  } catch {
    return blob;
  }
}

export function pickRecorderMimeType(): string | undefined {
  if (typeof MediaRecorder === 'undefined') return undefined;
  const candidates = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus'];
  return candidates.find(t => MediaRecorder.isTypeSupported(t));
}
