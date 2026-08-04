# Seamless texture LoRA training

Z-Image training supports an explicit texture objective on both the local
trainer and the scale-to-zero RunPod worker. Texture mode is intentionally a
dataset contract, not a prompt convention:

- every input is scored before model loading;
- examples below `min_tileability` are rejected;
- at least two accepted source tiles are required;
- captions receive a seamless-texture prefix when needed;
- cached latents are cyclically rolled on both axes every training step.

Use the original source tiles from `https://app.nz/textures`, not the 2x2 proof
images. A larger, diverse corpus (roughly 16-100 tiles) is recommended. Avoid a
dataset made entirely from repaired examples, because the LoRA can otherwise
learn the repair operator's edge-band signature.

```json
POST /train/from_urls
{
  "model": "zimage",
  "dataset_name": "stone-textures-v1",
  "image_urls": ["https://.../tile-a.png", "https://.../tile-b.webp"],
  "captions": ["weathered slate", "fine granite aggregate"],
  "dataset_mode": "texture",
  "min_tileability": 0.72,
  "lora_r": 16,
  "lora_alpha": 32,
  "learning_rate": 0.0001,
  "num_steps": 500,
  "batch_size": 1
}
```

The accelerated Cute/OmniServe inference transformer is not used for
backpropagation. Training uses the stock Diffusers Z-Image graph; the resulting
adapter can then be evaluated and served through the native Z-Image LoRA path.
Run a held-out evaluation with repeated 2x2 or 3x3 proofs before adding a trained
adapter to the public catalog.
