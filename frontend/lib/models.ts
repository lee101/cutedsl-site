export interface ModelParam {
  name: string;
  type: 'string' | 'int' | 'float' | 'string[]' | 'float[]' | 'float[][]' | 'object[]';
  required: boolean;
  default?: string | number;
  description: string;
  options?: string[];
  placeholder?: string;
}

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
    slug: 'zimage',
    name: 'Z-Image Turbo',
    description: 'Text-to-image generation powered by CuteZImage with fused Triton kernels. Generates high-quality 1024x1024 images in seconds.',
    category: 'image',
    responseType: 'image',
    pricingNote: '$1.00 per generation',
    pricingTier: 'first-party',
    params: [
      { name: 'prompt', type: 'string', required: true, description: 'Text description of the image to generate', placeholder: 'a cute cat wearing a tiny top hat, watercolor style' },
      { name: 'width', type: 'int', required: false, default: 1024, description: 'Image width in pixels (must be divisible by 64)' },
      { name: 'height', type: 'int', required: false, default: 1024, description: 'Image height in pixels (must be divisible by 64)' },
      { name: 'num_steps', type: 'int', required: false, default: 4, description: 'Number of denoising steps (more = higher quality, slower)' },
      { name: 'guidance', type: 'float', required: false, default: 3.5, description: 'Guidance scale — how closely to follow the prompt' },
      { name: 'seed', type: 'int', required: false, description: 'Random seed for reproducible results (0 = random)' },
    ],
    curlExample: `curl -X POST https://cutedsl.com/api/service \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer YOUR_API_KEY" \\
  -d '{
    "service": "zimage",
    "prompt": "a cute cat wearing a tiny top hat, watercolor style",
    "width": 1024,
    "height": 1024,
    "num_steps": 4,
    "guidance": 3.5
  }'`,
    responseExample: {
      result: { image_base64: '<base64-encoded WebP image>', width: 1024, height: 1024, format: 'webp' },
      credits_used: 1000,
      credits_remain: 49000,
      usd_equivalent: 1.0,
    },
  },
  {
    slug: 'chronos2',
    name: 'Chronos-2',
    description: 'Time series forecasting with CuteChronos2 acceleration. Achieves 27x speedup over baseline with custom Triton kernels.',
    category: 'timeseries',
    responseType: 'json',
    pricingNote: '$0.50 per forecast',
    pricingTier: 'first-party',
    params: [
      { name: 'values', type: 'float[]', required: true, description: 'Array of historical time series values', placeholder: '[1.2, 1.5, 1.3, 1.8, 2.1, 1.9, 2.4]' },
      { name: 'prediction_length', type: 'int', required: false, default: 12, description: 'Number of future time steps to forecast' },
      { name: 'quantile_levels', type: 'float[]', required: false, description: 'Quantile levels for prediction intervals', placeholder: '[0.1, 0.5, 0.9]' },
    ],
    curlExample: `curl -X POST https://cutedsl.com/api/service \\
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
    name: 'Kokoro TTS',
    description: 'High-quality text-to-speech with 20+ voices powered by Kokoro. Natural-sounding speech synthesis with adjustable speed.',
    category: 'audio',
    responseType: 'audio',
    pricingNote: '$0.10 per 100 characters',
    pricingTier: 'first-party',
    params: [
      { name: 'text', type: 'string', required: true, description: 'Text to convert to speech', placeholder: 'Hello! Welcome to CuteDSL, the fastest AI inference platform.' },
      { name: 'voice', type: 'string', required: false, description: 'Voice ID to use', options: ['af_nicole', 'af_sarah', 'af_bella', 'am_adam', 'am_michael', 'bf_emma', 'bf_isabella', 'bm_george', 'bm_lewis'] },
      { name: 'speed', type: 'float', required: false, default: 1.0, description: 'Speech speed multiplier (0.5 = half speed, 2.0 = double speed)' },
    ],
    curlExample: `curl -X POST https://cutedsl.com/api/service \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer YOUR_API_KEY" \\
  -d '{
    "service": "tts",
    "text": "Hello! Welcome to CuteDSL.",
    "voice": "af_nicole",
    "speed": 1.0
  }'`,
    responseExample: {
      result: { audio_base64: '<base64-encoded audio>', format: 'wav', duration_seconds: 2.1 },
      credits_used: 26,
      credits_remain: 49974,
      usd_equivalent: 0.026,
    },
  },
  {
    slug: 'stt',
    name: 'Speech-to-Text',
    description: 'Audio transcription powered by Gemma4. Accurately transcribes speech from audio URLs with support for multiple languages.',
    category: 'audio',
    responseType: 'json',
    pricingNote: '$0.20 per minute',
    pricingTier: 'first-party',
    params: [
      { name: 'audio_url', type: 'string', required: true, description: 'URL of the audio file to transcribe', placeholder: 'https://example.com/audio.mp3' },
    ],
    curlExample: `curl -X POST https://cutedsl.com/api/service \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer YOUR_API_KEY" \\
  -d '{
    "service": "stt",
    "audio_url": "https://example.com/audio.mp3"
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
    description: 'Gemma4 26B multimodal LLM for chat and vision tasks. Supports OpenAI-compatible message format with text and image inputs.',
    category: 'text',
    responseType: 'json',
    pricingNote: '$0.05 per request',
    pricingTier: 'first-party',
    params: [
      { name: 'messages', type: 'object[]', required: true, description: 'Array of messages in OpenAI format', placeholder: '[{"role": "user", "content": "What is CuteDSL?"}]' },
      { name: 'max_tokens', type: 'int', required: false, default: 1024, description: 'Maximum tokens to generate' },
      { name: 'temperature', type: 'float', required: false, default: 0.7, description: 'Sampling temperature (0 = deterministic, 1 = creative)' },
    ],
    curlExample: `curl -X POST https://cutedsl.com/api/service \\
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
    pricingNote: '$0.05 per image',
    pricingTier: 'first-party',
    params: [
      { name: 'image_url', type: 'string', required: true, description: 'URL of the image to caption', placeholder: 'https://example.com/photo.jpg' },
    ],
    curlExample: `curl -X POST https://cutedsl.com/api/service \\
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
    curlExample: `curl -X POST https://cutedsl.com/api/service \\
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
    curlExample: `curl -X POST https://cutedsl.com/api/service \\
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
    pricingNote: '$50.00 per training job',
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
    curlExample: `curl -X POST https://cutedsl.com/api/service \\
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
curl https://cutedsl.com/api/train/JOB_ID \\
  -H "Authorization: Bearer YOUR_API_KEY"`,
    responseExample: {
      result: { job_id: 'train_abc123', status: 'queued', model: 'chronos2', dataset_name: 'my-timeseries', estimated_time_minutes: 15 },
      credits_used: 50000,
      credits_remain: 0,
      usd_equivalent: 50.0,
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
