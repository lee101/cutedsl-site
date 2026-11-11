export interface ModelParam {
  name: string;
  type: 'string' | 'int' | 'float' | 'boolean' | 'string[]' | 'float[]' | 'float[][]' | 'object[]';
  required: boolean;
  default?: string | number | boolean;
  description: string;
  options?: string[];
  placeholder?: string;
  /** Render a drag/drop + mic + presigned-upload widget instead of a plain URL box. */
  upload?: 'audio' | 'image' | 'video' | 'file';
  /** One-click sample values shown next to the upload widget. */
  examples?: { label: string; url: string }[];
}

/** Public sample assets hosted on CuteDSL storage. */
export const SAMPLE_AUDIO_URL = 'https://appstatic.app.nz/cutedsl/samples/stt-sample-en.mp3';
export const SAMPLE_IMAGE_URL = 'https://cutedsl.cc/images/medium/b44f65a0e942f4d5_6b57661b.webp';

export interface ModelConfig {
  slug: string;
  name: string;
  description: string;
  category: 'image' | 'audio' | 'text' | 'timeseries' | 'video' | 'training';
  responseType: 'image' | 'audio' | 'json' | 'video';
  params: ModelParam[];
  curlExample: string;
  responseExample: Record<string, unknown>;
  pricingNote: string;
  pricingTier: 'first-party' | 'third-party';
}

export const MODELS: ModelConfig[] = [
  {
    slug: 'ra2',
    name: 'ra2 art generator',
    description: 'ra2 art generator — cinematic and illustration-specialised text-to-image at 1024x1024. Higher quality than Z-Image Turbo, roughly 2x slower per image. The default image service.',
    category: 'image',
    responseType: 'image',
    pricingNote: '$0.04 per generation (mirrors the Z-Image rate)',
    pricingTier: 'first-party',
    params: [
      { name: 'prompt', type: 'string', required: true, description: 'Text description of the image to generate', placeholder: 'cinematic portrait of a fox knight, volumetric light, 35mm film' },
      { name: 'negative_prompt', type: 'string', required: false, description: 'Concepts to avoid in the image', placeholder: 'blurry, watermark, low detail' },
      { name: 'width', type: 'int', required: false, default: 1024, description: 'Image width in pixels (rounded to a multiple of 32)' },
      { name: 'height', type: 'int', required: false, default: 1024, description: 'Image height in pixels (rounded to a multiple of 32)' },
      { name: 'num_steps', type: 'int', required: false, default: 20, description: 'Number of denoising steps (more = higher quality, slower)' },
      { name: 'guidance', type: 'float', required: false, default: 1.0, description: 'Guidance scale — how closely to follow the prompt' },
      { name: 'seed', type: 'int', required: false, description: 'Random seed for reproducible results (0 = random)' },
    ],
    curlExample: `curl -X POST https://cutedsl.cc/api/service \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer YOUR_API_KEY" \\
  -d '{
    "service": "ra2",
    "prompt": "cinematic portrait of a fox knight, volumetric light, 35mm film",
    "width": 1024,
    "height": 1024,
    "num_steps": 20,
    "guidance": 1.0
  }'`,
    responseExample: {
      result: { image_base64: '<base64-encoded WebP image>', width: 1024, height: 1024, format: 'webp', engine: 'ra2', seed: 12345, inference_time_ms: 2100, model: 'ra2' },
      credits_used: 1000,
      credits_remain: 49000,
      usd_equivalent: 0.04,
    },
  },
  {
    slug: 'ra2-edit',
    name: 'ra2 art generator (edit)',
    description: 'ra2 art generator style transfer and edit. Send a source image plus a prompt to restyle or refine it. Same engine and price as ra2.',
    category: 'image',
    responseType: 'image',
    pricingNote: '$0.04 per edit (same engine and price as ra2)',
    pricingTier: 'first-party',
    params: [
      { name: 'prompt', type: 'string', required: true, description: 'How to restyle or refine the source image', placeholder: 'turn this into a watercolor illustration, soft pastel palette' },
      { name: 'image_base64', type: 'string', required: true, description: 'Source image as raw base64 (no data: prefix)', placeholder: 'iVBORw0KGgoAAAANSUhEUg...' },
      { name: 'num_steps', type: 'int', required: false, default: 20, description: 'Number of denoising steps (more = higher quality, slower)' },
      { name: 'guidance', type: 'float', required: false, default: 1.0, description: 'Guidance scale — how closely to follow the prompt' },
      { name: 'seed', type: 'int', required: false, description: 'Random seed for reproducible results (0 = random)' },
    ],
    curlExample: `curl -X POST https://cutedsl.cc/api/service \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer YOUR_API_KEY" \\
  -d '{
    "service": "ra2-edit",
    "prompt": "turn this into a watercolor illustration, soft pastel palette",
    "image_base64": "iVBORw0KGgoAAAANSUhEUg..."
  }'`,
    responseExample: {
      result: { image_base64: '<base64-encoded WebP image>', width: 1024, height: 1024, format: 'webp', engine: 'ra2' },
      credits_used: 1000,
      credits_remain: 49000,
      usd_equivalent: 0.04,
    },
  },
  {
    slug: 'zimage',
    name: 'Z-Image Turbo',
    description: 'Text-to-image generation powered by CuteZImage with fused Triton kernels. Generates high-quality 1024x1024 images in seconds.',
    category: 'image',
    responseType: 'image',
    pricingNote: '$0.04 per generation; $0.10 for 20+ steps',
    pricingTier: 'first-party',
    params: [
      { name: 'prompt', type: 'string', required: true, description: 'Text description of the image to generate', placeholder: 'a cute cat wearing a tiny top hat, watercolor style' },
      { name: 'width', type: 'int', required: false, default: 1024, description: 'Image width in pixels (must be divisible by 64)' },
      { name: 'height', type: 'int', required: false, default: 1024, description: 'Image height in pixels (must be divisible by 64)' },
      { name: 'num_steps', type: 'int', required: false, default: 8, description: 'Number of denoising steps (more = higher quality, slower)' },
      { name: 'guidance', type: 'float', required: false, default: 3.5, description: 'Guidance scale — how closely to follow the prompt' },
      { name: 'seed', type: 'int', required: false, description: 'Random seed for reproducible results (0 = random)' },
    ],
    curlExample: `curl -X POST https://cutedsl.cc/api/service \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer YOUR_API_KEY" \\
  -d '{
    "service": "zimage",
    "prompt": "a cute cat wearing a tiny top hat, watercolor style",
    "width": 1024,
    "height": 1024,
    "num_steps": 8,
    "guidance": 3.5
  }'`,
    responseExample: {
      result: { image_base64: '<base64-encoded WebP image>', width: 1024, height: 1024, format: 'webp' },
      credits_used: 1000,
      credits_remain: 49000,
      usd_equivalent: 0.04,
    },
  },
  {
    slug: 'chronos2',
    name: 'Chronos-2',
    description: 'Time series forecasting with CuteChronos2 acceleration. Achieves 27x speedup over baseline with custom Triton kernels.',
    category: 'timeseries',
    responseType: 'json',
    pricingNote: '$0.002 per forecast',
    pricingTier: 'first-party',
    params: [
      { name: 'values', type: 'float[]', required: true, description: 'Array of historical time series values', placeholder: '[1.2, 1.5, 1.3, 1.8, 2.1, 1.9, 2.4]' },
      { name: 'prediction_length', type: 'int', required: false, default: 12, description: 'Number of future time steps to forecast' },
      { name: 'quantile_levels', type: 'float[]', required: false, description: 'Quantile levels for prediction intervals', placeholder: '[0.1, 0.5, 0.9]' },
    ],
    curlExample: `curl -X POST https://cutedsl.cc/api/service \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer YOUR_API_KEY" \\
  -d '{
    "service": "chronos2",
    "values": [1.2, 1.5, 1.3, 1.8, 2.1, 1.9, 2.4],
    "prediction_length": 12
  }'`,
    responseExample: {
      result: { forecast: [2.5, 2.6, 2.4, 2.7, 2.8], quantiles: { '0.1': [2.1, 2.2], '0.5': [2.5, 2.6], '0.9': [2.9, 3.0] } },
      credits_used: 500,
      credits_remain: 49500,
      usd_equivalent: 0.5,
    },
  },
  {
    slug: 'tts',
    name: 'Supertonic TTS',
    description: 'High-quality text-to-speech powered by text-generator.io Supertonic and Kokoro voices. Natural-sounding speech synthesis with language, speed, and step controls.',
    category: 'audio',
    responseType: 'audio',
    pricingNote: '$0.005 per 100 characters',
    pricingTier: 'first-party',
    params: [
      { name: 'text', type: 'string', required: true, description: 'Text to convert to speech', placeholder: 'Hello! Welcome to CuteDSL, the fastest AI inference platform.' },
      { name: 'voice', type: 'string', required: false, description: 'Voice ID to use. M1-M5/F1-F5 use Supertonic; Kokoro voices such as af_nicole are still supported.', options: ['M1', 'M2', 'M3', 'M4', 'M5', 'F1', 'F2', 'F3', 'F4', 'F5', 'af_nicole', 'af_sarah', 'af_bella', 'am_adam', 'am_michael', 'bf_emma', 'bf_isabella', 'bm_george', 'bm_lewis'] },
      { name: 'language', type: 'string', required: false, default: 'en', description: 'Supertonic language code. Kokoro derives language from the voice.', options: ['en', 'ko', 'ja', 'ar', 'bg', 'cs', 'da', 'de', 'el', 'es', 'et', 'fi', 'fr', 'hi', 'hr', 'hu', 'id', 'it', 'lt', 'lv', 'nl', 'pl', 'pt', 'ro', 'ru', 'sk', 'sl', 'sv', 'tr', 'uk', 'vi'] },
      { name: 'speed', type: 'float', required: false, default: 1.0, description: 'Speech speed multiplier (0.5 = half speed, 2.0 = double speed)' },
      { name: 'steps', type: 'int', required: false, default: 4, description: 'Supertonic synthesis steps' },
    ],
    curlExample: `curl -X POST https://cutedsl.cc/api/service \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer YOUR_API_KEY" \\
  -d '{
    "service": "tts",
    "text": "Hello! Welcome to CuteDSL.",
    "voice": "M1",
    "language": "en",
    "speed": 1.0,
    "steps": 4
  }'`,
    responseExample: {
      result: { audio_base64: '<base64-encoded audio>', format: 'wav', voice: 'M1', language: 'en', characters: 25 },
      credits_used: 26,
      credits_remain: 49974,
      usd_equivalent: 0.026,
    },
  },
  {
    slug: 'stt',
    name: 'Speech-to-Text',
    description: 'Audio transcription powered by Gemma4. Record from your mic or drop a file — it uploads straight to CuteDSL storage and transcribes from the resulting URL. Supports multiple languages.',
    category: 'audio',
    responseType: 'json',
    pricingNote: '$0.02 per minute',
    pricingTier: 'first-party',
    params: [
      {
        name: 'audio_url',
        type: 'string',
        required: true,
        description: 'URL of the audio file to transcribe. Use the recorder/uploader below, or pass any public mp3, wav, m4a, ogg or webm URL.',
        placeholder: 'https://appstatic.app.nz/cutedsl/samples/stt-sample-en.mp3',
        upload: 'audio',
        examples: [{ label: 'Sample speech (12s)', url: SAMPLE_AUDIO_URL }],
      },
    ],
    curlExample: `# 1. Get a presigned upload URL (skip if your audio is already public)
curl "https://cutedsl.cc/api/uploads/presign?filename=speech.wav&content_type=audio/wav&dataset=stt" \\
  -H "Authorization: Bearer YOUR_API_KEY"
# -> {"upload_url": "https://...r2.cloudflarestorage.com/...", "public_url": "https://appstatic.app.nz/cutedsl/uploads/..."}

# 2. PUT the file straight to storage (no proxy, no size limit on our API)
curl -X PUT "PRESIGNED_UPLOAD_URL" \\
  -H "Content-Type: audio/wav" \\
  --data-binary @speech.wav

# 3. Transcribe the public URL
curl -X POST https://cutedsl.cc/api/service \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer YOUR_API_KEY" \\
  -d '{
    "service": "stt",
    "audio_url": "https://appstatic.app.nz/cutedsl/samples/stt-sample-en.mp3"
  }'`,
    responseExample: {
      result: { text: 'Hello, this is a transcription example.', language: 'en', duration_seconds: 15.3 },
      credits_used: 51,
      credits_remain: 49949,
      usd_equivalent: 0.051,
    },
  },
  {
    slug: 'gemma4',
    name: 'Gemma4 Chat',
    description: 'Google Gemma 4 multimodal LLM for chat and vision tasks — an efficient mixture-of-experts (~4B active params). Supports OpenAI-compatible message format with text and image inputs.',
    category: 'text',
    responseType: 'json',
    pricingNote: '$0.01 per request',
    pricingTier: 'first-party',
    params: [
      { name: 'messages', type: 'object[]', required: true, description: 'Array of messages in OpenAI format', placeholder: '[{"role": "user", "content": "What is CuteDSL?"}]' },
      { name: 'max_tokens', type: 'int', required: false, default: 1024, description: 'Maximum tokens to generate' },
      { name: 'temperature', type: 'float', required: false, default: 0.7, description: 'Sampling temperature (0 = deterministic, 1 = creative)' },
    ],
    curlExample: `curl -X POST https://cutedsl.cc/api/service \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer YOUR_API_KEY" \\
  -d '{
    "service": "gemma4",
    "messages": [{"role": "user", "content": "What is CuteDSL?"}],
    "max_tokens": 1024,
    "temperature": 0.7
  }'`,
    responseExample: {
      result: { choices: [{ message: { role: 'assistant', content: 'CuteDSL is an ML acceleration framework...' } }], usage: { prompt_tokens: 12, completion_tokens: 45 } },
      credits_used: 50,
      credits_remain: 49950,
      usd_equivalent: 0.05,
    },
  },
  {
    slug: 'caption',
    name: 'Image Caption',
    description: 'Automatic image captioning powered by GitBase. Generates descriptive captions for any image URL.',
    category: 'text',
    responseType: 'json',
    pricingNote: '$0.01 per image',
    pricingTier: 'first-party',
    params: [
      {
        name: 'image_url',
        type: 'string',
        required: true,
        description: 'URL of the image to caption. Drop a file below to upload it to CuteDSL storage first.',
        placeholder: 'https://example.com/photo.jpg',
        upload: 'image',
        examples: [{ label: 'Sample image', url: SAMPLE_IMAGE_URL }],
      },
    ],
    curlExample: `curl -X POST https://cutedsl.cc/api/service \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer YOUR_API_KEY" \\
  -d '{
    "service": "caption",
    "image_url": "https://example.com/photo.jpg"
  }'`,
    responseExample: {
      result: { caption: 'A golden retriever playing fetch in a sunny park with green grass.' },
      credits_used: 50,
      credits_remain: 49950,
      usd_equivalent: 0.05,
    },
  },
  {
    slug: 'ltx_video',
    name: 'LTX Video',
    description: 'Text-to-video generation using LTX 2.3. Creates ~6 second 1080p videos at 25fps from text prompts.',
    category: 'video',
    responseType: 'video',
    pricingNote: '$0.30 per ~6s video',
    pricingTier: 'third-party',
    params: [
      { name: 'prompt', type: 'string', required: true, description: 'Text description of the video to generate', placeholder: 'a timelapse of clouds rolling over mountains at sunset' },
    ],
    curlExample: `curl -X POST https://cutedsl.cc/api/service \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer YOUR_API_KEY" \\
  -d '{
    "service": "ltx_video",
    "prompt": "a timelapse of clouds rolling over mountains at sunset"
  }'`,
    responseExample: {
      result: { video_url: 'https://fal.media/files/example/video.mp4', duration: 6, resolution: '1080p', fps: 25 },
      credits_used: 300,
      credits_remain: 49700,
      usd_equivalent: 0.3,
    },
  },
  {
    slug: 'video_generate',
    name: 'Image + Video Studio',
    description: 'Generate video from a prompt or animate a still image through OpenPaths. Results are re-encoded to storage-efficient AV1 WebM and published to CuteDSL object storage.',
    category: 'video',
    responseType: 'video',
    pricingNote: 'From $0.08 per video; model-dependent',
    pricingTier: 'third-party',
    params: [
      { name: 'prompt', type: 'string', required: true, description: 'Describe the scene and the motion you want.', placeholder: 'slow camera push-in as flowers glow and sway in the breeze' },
      { name: 'model', type: 'string', required: false, default: 'auto-video', description: 'OpenPaths video model or automatic routing.', options: ['auto-video', 'ltx-video', 'ltx-2', 'ltx-2.3-image-to-video'] },
      {
        name: 'image_url',
        type: 'string',
        required: false,
        description: 'Public still-image URL to animate. Required for LTX 2.3 image-to-video. Upload below to get one.',
        placeholder: 'https://example.com/still.webp',
        upload: 'image',
        examples: [{ label: 'Sample still', url: SAMPLE_IMAGE_URL }],
      },
      { name: 'aspect_ratio', type: 'string', required: false, default: '16:9', description: 'Output frame ratio.', options: ['16:9', '9:16', '1:1', '4:3'] },
      { name: 'duration', type: 'int', required: false, default: 5, description: 'Requested clip duration in seconds (up to 10).' },
      { name: 'output_format', type: 'string', required: false, default: 'webm', description: 'CuteDSL returns an AV1 WebM optimized on its own host.' },
    ],
    curlExample: `curl -X POST https://cutedsl.cc/api/service \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{
    "service": "video_generate",
    "model": "auto-video",
    "prompt": "slow camera push-in as flowers glow and sway",
    "image_url": "https://example.com/still.webp",
    "aspect_ratio": "16:9",
    "duration": 5
  }'`,
    responseExample: {
      result: { video_url: 'https://appstatic.app.nz/cutedsl/uploads/user/videos/example.webm', original_video_url: 'https://provider.example/source.mp4', codec: 'av1', output_format: 'webm' },
      credits_used: 15,
      credits_remain: 4985,
      usd_equivalent: 0.15,
    },
  },
  {
    slug: 'h3_video',
    name: 'MiniMax H3 Video',
    description: 'Text-to-video and image-to-video through the shared app.nz H3 Cog, with first/last-frame control, scheduler-level seamless loops, native stereo audio, and GPU AV1 delivery.',
    category: 'video',
    responseType: 'video',
    pricingNote: '$2.688/GPU-hour, metered by completed app.nz execution time (app.nz price + 20%)',
    pricingTier: 'third-party',
    params: [
      { name: 'prompt', type: 'string', required: true, description: 'Scene, action, camera, style, and optional audio direction.', placeholder: 'A locked-off living photograph of a waterfall; only water and nearby leaves move in a subtle seamless loop.' },
      { name: 'first_frame', type: 'string', required: false, description: 'Public start-frame URL for image-to-video. Required for loop mode.', upload: 'image', examples: [{ label: 'Sample still', url: SAMPLE_IMAGE_URL }] },
      { name: 'last_frame', type: 'string', required: false, description: 'Optional public target final-frame URL.', upload: 'image' },
      { name: 'aspect_ratio', type: 'string', required: false, default: '16:9', description: 'Output frame ratio.', options: ['16:9', '9:16', '1:1', '4:3', '3:4', '21:9'] },
      { name: 'size', type: 'string', required: false, default: 'balanced', description: 'Preview, balanced, or native 768px short-edge canvas.', options: ['preview', 'balanced', 'native'] },
      { name: 'duration', type: 'int', required: false, default: 5, description: 'Clip length from 4 to 15 seconds.' },
      { name: 'num_steps', type: 'int', required: false, default: 20, description: 'Sampling steps from 8 to 30.' },
      { name: 'seed', type: 'int', required: false, description: 'Optional deterministic seed.' },
      { name: 'structured_prompt', type: 'boolean', required: false, default: true, description: 'Expand concise input into H3 structured prompting.' },
      { name: 'loop', type: 'boolean', required: false, default: false, description: 'Reuse first_frame as the scheduler final-frame condition.' },
      { name: 'include_audio', type: 'boolean', required: false, default: true, description: 'Generate H3 native stereo audio.' },
      { name: 'output_format', type: 'string', required: false, default: 'webm-av1', description: 'GPU delivery codec.', options: ['webm-av1', 'mp4-h264'] },
      { name: 'encode_quality', type: 'int', required: false, default: 26, description: 'NVENC constant quality from 16 to 45; lower is higher quality.' },
    ],
    curlExample: `curl -X POST https://cutedsl.cc/api/service \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{
    "service": "h3_video",
    "prompt": "A subtle living photograph of a waterfall",
    "first_frame": "https://example.com/start.webp",
    "loop": true,
    "include_audio": true,
    "size": "balanced",
    "duration": 5,
    "num_steps": 20,
    "output_format": "webm-av1"
  }'`,
    responseExample: {
      result: { job_id: 'video_...', status: 'queued', status_url: '/api/video-jobs/video_...' },
      credits_used: 0,
      settlement: 'completed app.nz prediction cost plus 20%',
      price_usd_per_gpu_hour: 2.688,
    },
  },
  {
    slug: 'flux_image',
    name: 'Flux Schnell',
    description: 'Fast image generation using Flux Schnell via fal.ai. Produces 1024x1024 images with minimal latency.',
    category: 'image',
    responseType: 'image',
    pricingNote: '$0.04 per image',
    pricingTier: 'third-party',
    params: [
      { name: 'prompt', type: 'string', required: true, description: 'Text description of the image to generate', placeholder: 'a futuristic cityscape at night with neon lights' },
    ],
    curlExample: `curl -X POST https://cutedsl.cc/api/service \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer YOUR_API_KEY" \\
  -d '{
    "service": "flux_image",
    "prompt": "a futuristic cityscape at night with neon lights"
  }'`,
    responseExample: {
      result: { image_url: 'https://fal.media/files/example/image.webp', width: 1024, height: 1024 },
      credits_used: 40,
      credits_remain: 49960,
      usd_equivalent: 0.04,
    },
  },
  {
    slug: 'lora_training',
    name: 'LoRA Training',
    description: 'Fine-tune models with LoRA adapters. Train custom adapters for Z-Image or Chronos-2 on your own data.',
    category: 'training',
    responseType: 'json',
    pricingNote: '$5.00 per training job',
    pricingTier: 'first-party',
    params: [
      { name: 'model', type: 'string', required: true, description: 'Base model to fine-tune', options: ['zimage', 'chronos2'] },
      { name: 'dataset_name', type: 'string', required: true, description: 'Name for the training dataset', placeholder: 'my-custom-style' },
      { name: 'train_values', type: 'float[][]', required: false, description: 'Training data (for chronos2 — array of time series)', placeholder: '[[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]' },
      { name: 'lora_r', type: 'int', required: false, default: 8, description: 'LoRA rank (higher = more capacity, more compute)' },
      { name: 'lora_alpha', type: 'int', required: false, default: 16, description: 'LoRA alpha scaling factor' },
      { name: 'learning_rate', type: 'float', required: false, default: 0.0001, description: 'Training learning rate' },
      { name: 'train_steps', type: 'int', required: false, default: 1000, description: 'Number of training steps' },
      { name: 'train_batch', type: 'int', required: false, default: 4, description: 'Training batch size' },
    ],
    curlExample: `curl -X POST https://cutedsl.cc/api/service \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer YOUR_API_KEY" \\
  -d '{
    "service": "lora_training",
    "model": "chronos2",
    "dataset_name": "my-timeseries",
    "train_values": [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]],
    "lora_r": 8,
    "train_steps": 1000
  }'

# Check training status:
curl https://cutedsl.cc/api/train/JOB_ID \\
  -H "Authorization: Bearer YOUR_API_KEY"`,
    responseExample: {
      result: { job_id: 'train_abc123', status: 'queued', model: 'chronos2', dataset_name: 'my-timeseries', estimated_time_minutes: 15 },
      credits_used: 5000,
      credits_remain: 45000,
      usd_equivalent: 5.0,
    },
  },
];

export const MODEL_MAP: Record<string, ModelConfig> = Object.fromEntries(MODELS.map(m => [m.slug, m]));
export const MODEL_SLUGS: string[] = MODELS.map(m => m.slug);

export const CATEGORY_LABELS: Record<string, string> = {
  image: 'Image',
  audio: 'Audio',
  text: 'Text',
  timeseries: 'Time Series',
  video: 'Video',
  training: 'Training',
};

export const CATEGORY_COLORS: Record<string, string> = {
  image: 'bg-pink-100 text-pink-700',
  audio: 'bg-purple-100 text-purple-700',
  text: 'bg-blue-100 text-blue-700',
  timeseries: 'bg-cyan-100 text-cyan-700',
  video: 'bg-orange-100 text-orange-700',
  training: 'bg-green-100 text-green-700',
};
