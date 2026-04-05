'use client';

import Link from 'next/link';
import Image from 'next/image';
import { Wand2, Sparkles, LineChart, ImageIcon, Zap, Cpu, Timer, MemoryStick, ArrowLeft, Server, Search } from 'lucide-react';

const IMG_BASE = 'https://appstatic.app.nz/cutedsl/images';

const chronosBenchmarks = [
  { name: 'Original Chronos2Pipeline', latency: '41.98 ms', speedup: '1.0x', memory: '248 MB', mode: 'Baseline' },
  { name: 'CuteChronos2 (eager)', latency: '19.15 ms', speedup: '2.19x', memory: '247 MB', mode: 'Eager' },
  { name: 'CuteChronos2 (torch.compile)', latency: '1.55 ms', speedup: '27.1x', memory: '237 MB', mode: 'Compiled' },
  { name: 'CuteChronos2 + TQ4 (compiled)', latency: '16.40 ms', speedup: '2.56x', memory: '~200 MB', mode: 'Quantized' },
];

const chronosKernels = [
  { name: 'Unscaled Tiled Attention', description: 'FlashAttention-style tiling without 1/sqrt(d_k) scaling. Avoids materializing S×S attention matrix. FP32 softmax for numerical stability.', file: 'triton_kernels/attention.py' },
  { name: 'RMS LayerNorm', description: 'T5-style RMS normalization in a single Triton kernel. FP32 variance computation, no mean subtraction.', file: 'triton_kernels/rms_layernorm.py' },
  { name: 'Fused RoPE', description: 'Rotary Position Embeddings fused into one kernel: inv_freq computation + cos/sin + Q/K rotation.', file: 'triton_kernels/rope.py' },
  { name: 'Fused LayerNorm + Linear', description: 'Merges RMS LayerNorm and linear projection. Eliminates the normalized intermediate tensor entirely.', file: 'triton_kernels/fused_layernorm_linear.py' },
  { name: 'Fused MLP', description: 'Two-layer MLP with ReLU activation in a single kernel pass. Avoids 3072-wide intermediate buffer allocation.', file: 'triton_kernels/fused_mlp.py' },
  { name: 'Fused Output Transform', description: 'Output rearrange + sinh + unscale in a single kernel pass over the output tensor.', file: 'triton_kernels/fused_output.py' },
  { name: 'Fused Preprocessing', description: 'NaN-aware preprocessing pipeline. Two-phase: shared memory reduction for statistics, then transform.', file: 'triton_kernels/fused_preprocess.py' },
  { name: 'CUDA Preprocessing', description: 'C++/CUDA NaN-aware normalization and patching with shared memory reductions for per-series statistics.', file: 'cpp/preprocessing.cu' },
];

const zimagKernels = [
  { name: 'Fused SiLU-Gated FFN', description: 'Fuses silu(w1(x)) * w3(x) in a single kernel. Eliminates 10240-wide intermediate allocation that dominates memory bandwidth.', file: 'triton_kernels/fused_silu_gate_ffn.py' },
  { name: 'Fused AdaLN + RMS Norm', description: 'Timestep conditioning fused with normalization in one pass instead of separate modulation + norm.', file: 'triton_kernels/fused_adaln_norm.py' },
  { name: 'Complex-valued RoPE', description: 'Fuses reshape + complex multiply + flatten for Z-Image\'s complex multiplication convention. Avoids intermediate complex tensor allocations.', file: 'triton_kernels/rope_complex.py' },
  { name: 'RMS Norm', description: 'Triton-accelerated RMS normalization with FP32 variance and optional weight scaling.', file: 'triton_kernels/rms_norm.py' },
  { name: 'CUDA RMS Norm', description: 'Vectorized 128-bit loads/stores (bfloat162, half2, float4) for maximum memory bandwidth.', file: 'csrc/cute_rms_norm.cu' },
  { name: 'CUDA SiLU Gate', description: 'Vectorized SiLU activation + gating for float32, float16, and bfloat16 with coalesced memory access.', file: 'csrc/cute_silu_gate.cu' },
  { name: 'Fused QKV + Norm + RoPE', description: 'Combined QKV projection, normalization, and RoPE in a single multi-operation fusion kernel.', file: 'triton_kernels/fused_qkv_norm_rope.py' },
];

const zimagePipelineBenchmarks = [
  { name: 'Python (CPU offload)', mode: 'Eager', latency: '~32,000 ms', speedup: '1.0x', memory: '~7 GB' },
  { name: 'Python (GPU resident)', mode: 'Eager', latency: '~31,500 ms', speedup: '1.02x', memory: '~18 GB' },
  { name: 'Python + CuteDSL Kernels', mode: 'Fused', latency: '~30,000 ms', speedup: '1.07x', memory: '~18 GB' },
  { name: 'Go+C (Python embed)', mode: 'CGO Bridge', latency: '~31,200 ms', speedup: '1.03x', memory: '~18 GB' },
  { name: 'Go+C (LibTorch native)', mode: 'Projected', latency: '~100 ms', speedup: '~320x', memory: '~14 GB' },
  { name: 'Go+C + NVFP4', mode: 'Projected', latency: '~60 ms', speedup: '~533x', memory: '~8 GB' },
];

const loraSearchBenchmarks = [
  { engine: 'Keyword (Python)', latency: '<0.1 ms', accuracy: 'Good' },
  { engine: 'Embedding (Python, sentence-transformers)', latency: '4 ms', accuracy: 'Excellent' },
  { engine: 'Embedding (Go, gobed)', latency: '<1 ms', accuracy: 'Excellent' },
  { engine: 'Embedding + Negative (Python)', latency: '5 ms', accuracy: 'Best' },
  { engine: 'Embedding + Negative (Go, gobed)', latency: '<1 ms', accuracy: 'Best' },
];

const accelerationTechniques = [
  {
    name: 'Latent Teleportation',
    module: 'latentteleport/',
    status: 'Research',
    description: 'Pre-compute and cache intermediate diffusion latents for common prompt patterns. Interpolate between cached latents using SLERP or neural combiners, then refine from the interpolated latent with fewer denoising steps. Reduces effective diffusion steps from ~20 to ~5.',
    techniques: ['SLERP interpolation (custom Triton kernel)', 'Neural network combiners', 'Tree-based hierarchical combination', 'NLP / curated / CLIP tokenizer strategies', 'Confidence estimation for cache hits'],
  },
  {
    name: 'TurboQuant',
    module: 'tubroquant/',
    status: 'Research',
    description: 'Vector quantization for KV cache and attention optimization. MSE and product quantization modes with Hadamard rotation for improved compression. 2-16x compression with configurable bit-widths.',
    techniques: ['MSE vector quantization with codebook lookup', 'Product (residual) quantization', 'Hadamard rotation pre-processing', 'Norm-aware reconstruction', 'CUDA kernel for quantized QK attention scores', 'Bit-packing with warp-level reductions'],
  },
  {
    name: 'torch.compile + CUDA Graphs',
    module: 'cutechronos/model.py',
    status: 'Production',
    description: 'Captures the full forward pass as a CUDA graph via torch.compile with reduce-overhead mode. Eliminates kernel launch overhead entirely. Requires fixed input shapes. Achieves 24.4x speedup on CuteChronos2.',
    techniques: ['reduce-overhead compile mode', 'CUDA graph capture', 'Fixed-shape inference', 'Zero kernel launch overhead'],
  },
  {
    name: 'NVFP4 Quantization',
    module: 'inference/server.py',
    status: 'Production',
    description: '4-bit floating point quantization for RTX 5090 Blackwell architecture via torchao. Per-block scaling gives ~2x memory reduction and faster matmuls on SM100+ GPUs.',
    techniques: ['NVFP4 weight-only quantization', 'Per-block scaling (block_size=32)', 'torchao integration', 'RTX 5090 Blackwell SM100+'],
  },
  {
    name: 'Kernel Fusion',
    module: 'cutechronos/, cutezimage/',
    status: 'Production',
    description: 'Fuse multiple operations into single Triton/CUDA kernels to eliminate intermediate tensor allocations and reduce memory bandwidth pressure. Core technique across all CuteDSL modules.',
    techniques: ['LayerNorm + Linear fusion', 'SiLU + Gate multiply fusion', 'AdaLN + Normalization fusion', 'RoPE + QKV fusion', 'Preprocessing pipeline fusion'],
  },
  {
    name: 'Vectorized CUDA',
    module: 'cutezimage/csrc/',
    status: 'Production',
    description: '128-bit vectorized loads and stores using bfloat162, half2, and float4 types. Maximizes memory bandwidth utilization on modern GPUs.',
    techniques: ['128-bit vectorized loads/stores', 'Warp-level reductions', 'Shared memory optimizations', 'Coalesced access patterns'],
  },
  {
    name: 'stable-diffusion.cpp',
    module: 'diffusionz/',
    status: 'In Progress',
    description: 'Pure C++ stable diffusion inference using GGML-style quantization. Goal: run diffusion models on CPU or with minimal GPU, similar to how llama.cpp democratized LLM inference. DiffusionZ C API (diffusionz_c_api.h) is implemented with LibTorch backend; evaluating stable-diffusion.cpp as an alternative lighter backend.',
    techniques: ['GGML-style quantization (Q4, Q8)', 'CPU inference path', 'Metal/CUDA backends', 'DiffusionZ C API (implemented)', 'LibTorch C++ backend', 'CGO bridge to Go server'],
  },
];

export default function EvalsPage() {
  return (
    <div className="min-h-screen bg-pink-50">
      {/* Nav */}
      <nav className="w-full p-6 flex justify-between items-center max-w-7xl mx-auto">
        <Link href="/" className="flex items-center gap-2">
          <Image src={`${IMG_BASE}/logo.webp`} alt="CuteDSL" width={40} height={40} className="rounded-lg" />
          <span className="font-fredoka text-3xl font-bold text-pink-600">CuteDSL</span>
        </Link>
        <div className="flex gap-6 font-bold text-slate-700">
          <Link href="/" className="hover:text-pink-500 transition-colors flex items-center gap-1"><ArrowLeft size={16} /> Home</Link>
          <Link href="/blog" className="hover:text-purple-500 transition-colors">Blog</Link>
        </div>
      </nav>

      <main className="max-w-7xl mx-auto px-6 pb-24">
        {/* Hero */}
        <div className="text-center py-16">
          <div className="inline-flex items-center gap-2 bg-white/80 px-4 py-2 rounded-full text-pink-600 font-bold mb-6 border border-pink-200">
            <Sparkles size={16} />
            <span>Benchmarks &amp; Acceleration Research</span>
          </div>
          <h1 className="font-fredoka text-5xl lg:text-7xl font-bold text-slate-800 mb-4">Evals</h1>
          <p className="text-xl text-slate-600 max-w-3xl mx-auto font-medium">
            Performance benchmarks for every CuteDSL-accelerated model and a breakdown of each acceleration technique we&apos;re researching and shipping.
          </p>
        </div>

        {/* CuteChronos2 Benchmarks */}
        <section className="mb-20">
          <div className="flex items-center gap-3 mb-8">
            <div className="bg-cyan-100 p-3 rounded-2xl text-cyan-600"><LineChart size={28} /></div>
            <div>
              <h2 className="font-fredoka text-3xl font-bold text-slate-800">CuteChronos2</h2>
              <p className="text-slate-500 font-medium">SOTA time series forecasting &mdash; RTX 5090, B=1, context=768, base model (768 d_model, 12 layers), H=16</p>
            </div>
          </div>

          <div className="overflow-x-auto mb-10">
            <table className="w-full bg-white rounded-2xl shadow-sm border border-slate-100 overflow-hidden">
              <thead className="bg-slate-50">
                <tr>
                  <th className="text-left px-6 py-4 font-bold text-slate-700">Configuration</th>
                  <th className="text-left px-6 py-4 font-bold text-slate-700">Mode</th>
                  <th className="text-right px-6 py-4 font-bold text-slate-700">Latency</th>
                  <th className="text-right px-6 py-4 font-bold text-slate-700">Speedup</th>
                  <th className="text-right px-6 py-4 font-bold text-slate-700">Memory</th>
                </tr>
              </thead>
              <tbody>
                {chronosBenchmarks.map((b, i) => (
                  <tr key={i} className={`border-t border-slate-100 ${i === 2 ? 'bg-cyan-50' : ''}`}>
                    <td className="px-6 py-4 font-medium text-slate-800">{b.name}</td>
                    <td className="px-6 py-4"><span className={`text-xs font-bold px-2 py-1 rounded ${i === 2 ? 'bg-cyan-200 text-cyan-800' : 'bg-slate-100 text-slate-600'}`}>{b.mode}</span></td>
                    <td className="px-6 py-4 text-right font-mono font-bold text-slate-700">{b.latency}</td>
                    <td className="px-6 py-4 text-right font-mono font-bold text-cyan-600">{b.speedup}</td>
                    <td className="px-6 py-4 text-right font-mono text-slate-500">{b.memory}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <h3 className="font-bold text-xl text-slate-800 mb-4">Custom Kernels (8 Triton + 1 CUDA)</h3>
          <div className="grid md:grid-cols-2 gap-4">
            {chronosKernels.map((k, i) => (
              <div key={i} className="bg-white p-5 rounded-xl border border-slate-100 shadow-sm">
                <div className="flex items-start justify-between mb-2">
                  <h4 className="font-bold text-slate-800">{k.name}</h4>
                  <code className="text-xs bg-slate-100 px-2 py-1 rounded text-slate-500 shrink-0 ml-2">{k.file}</code>
                </div>
                <p className="text-sm text-slate-600">{k.description}</p>
              </div>
            ))}
          </div>
        </section>

        {/* CuteZImage Benchmarks */}
        <section className="mb-20">
          <div className="flex items-center gap-3 mb-8">
            <div className="bg-pink-100 p-3 rounded-2xl text-pink-600"><ImageIcon size={28} /></div>
            <div>
              <h2 className="font-fredoka text-3xl font-bold text-slate-800">CuteZImage</h2>
              <p className="text-slate-500 font-medium">Z-Image Turbo transformer &mdash; 30 layers, dim=3840, 30 heads, SiLU-gated FFN (hidden=10240)</p>
            </div>
          </div>

          <div className="overflow-x-auto mb-10">
            <table className="w-full bg-white rounded-2xl shadow-sm border border-slate-100 overflow-hidden">
              <thead className="bg-slate-50">
                <tr>
                  <th className="text-left px-6 py-4 font-bold text-slate-700">Configuration</th>
                  <th className="text-left px-6 py-4 font-bold text-slate-700">Mode</th>
                  <th className="text-right px-6 py-4 font-bold text-slate-700">Latency</th>
                  <th className="text-right px-6 py-4 font-bold text-slate-700">Speedup</th>
                  <th className="text-right px-6 py-4 font-bold text-slate-700">VRAM</th>
                </tr>
              </thead>
              <tbody>
                <tr className="border-t border-slate-100">
                  <td className="px-6 py-4 font-medium text-slate-800">Original Z-Image Turbo</td>
                  <td className="px-6 py-4"><span className="text-xs font-bold px-2 py-1 rounded bg-slate-100 text-slate-600">Baseline</span></td>
                  <td className="px-6 py-4 text-right font-mono font-bold text-slate-700">105.79 ms</td>
                  <td className="px-6 py-4 text-right font-mono font-bold text-slate-500">1.0x</td>
                  <td className="px-6 py-4 text-right font-mono text-slate-500">11,983 MB</td>
                </tr>
                <tr className="border-t border-slate-100">
                  <td className="px-6 py-4 font-medium text-slate-800">CuteZImage (eager)</td>
                  <td className="px-6 py-4"><span className="text-xs font-bold px-2 py-1 rounded bg-slate-100 text-slate-600">Eager</span></td>
                  <td className="px-6 py-4 text-right font-mono font-bold text-slate-700">93.30 ms</td>
                  <td className="px-6 py-4 text-right font-mono font-bold text-pink-600">1.13x</td>
                  <td className="px-6 py-4 text-right font-mono text-slate-500">11,977 MB</td>
                </tr>
                <tr className="border-t border-slate-100 bg-pink-50">
                  <td className="px-6 py-4 font-medium text-slate-800">CuteZImage (torch.compile)</td>
                  <td className="px-6 py-4"><span className="text-xs font-bold px-2 py-1 rounded bg-pink-200 text-pink-800">Compiled</span></td>
                  <td className="px-6 py-4 text-right font-mono font-bold text-slate-700">90.99 ms</td>
                  <td className="px-6 py-4 text-right font-mono font-bold text-pink-600">1.16x</td>
                  <td className="px-6 py-4 text-right font-mono text-slate-500">11,883 MB</td>
                </tr>
              </tbody>
            </table>
            <p className="text-xs text-slate-400 mt-2">Output correctness: max_abs_error = 0.0 (bit-exact match with original)</p>
          </div>

          <h3 className="font-bold text-xl text-slate-800 mb-4">Custom Kernels (5 Triton + 3 CUDA)</h3>
          <div className="grid md:grid-cols-2 gap-4">
            {zimagKernels.map((k, i) => (
              <div key={i} className="bg-white p-5 rounded-xl border border-slate-100 shadow-sm">
                <div className="flex items-start justify-between mb-2">
                  <h4 className="font-bold text-slate-800">{k.name}</h4>
                  <code className="text-xs bg-slate-100 px-2 py-1 rounded text-slate-500 shrink-0 ml-2">{k.file}</code>
                </div>
                <p className="text-sm text-slate-600">{k.description}</p>
              </div>
            ))}
          </div>
        </section>

        {/* Z-Image Inference Pipeline */}
        <section className="mb-20">
          <div className="flex items-center gap-3 mb-8">
            <div className="bg-orange-100 p-3 rounded-2xl text-orange-600"><Server size={28} /></div>
            <div>
              <h2 className="font-fredoka text-3xl font-bold text-slate-800">Z-Image Inference Pipeline</h2>
              <p className="text-slate-500 font-medium">End-to-end generation latency &mdash; Python server vs Go+C migration &mdash; RTX 5090, 9-step Z-Image Turbo</p>
            </div>
          </div>

          <div className="overflow-x-auto mb-10">
            <table className="w-full bg-white rounded-2xl shadow-sm border border-slate-100 overflow-hidden">
              <thead className="bg-slate-50">
                <tr>
                  <th className="text-left px-6 py-4 font-bold text-slate-700">Configuration</th>
                  <th className="text-left px-6 py-4 font-bold text-slate-700">Mode</th>
                  <th className="text-right px-6 py-4 font-bold text-slate-700">Latency</th>
                  <th className="text-right px-6 py-4 font-bold text-slate-700">Speedup</th>
                  <th className="text-right px-6 py-4 font-bold text-slate-700">Memory</th>
                </tr>
              </thead>
              <tbody>
                {zimagePipelineBenchmarks.map((b, i) => (
                  <tr key={i} className={`border-t border-slate-100 ${i >= 4 ? 'bg-orange-50' : ''}`}>
                    <td className="px-6 py-4 font-medium text-slate-800">{b.name}</td>
                    <td className="px-6 py-4"><span className={`text-xs font-bold px-2 py-1 rounded ${
                      b.mode === 'Projected' ? 'bg-orange-200 text-orange-800' :
                      b.mode === 'Fused' ? 'bg-pink-200 text-pink-800' :
                      b.mode === 'CGO Bridge' ? 'bg-blue-100 text-blue-800' :
                      'bg-slate-100 text-slate-600'
                    }`}>{b.mode}</span></td>
                    <td className="px-6 py-4 text-right font-mono font-bold text-slate-700">{b.latency}</td>
                    <td className="px-6 py-4 text-right font-mono font-bold text-orange-600">{b.speedup}</td>
                    <td className="px-6 py-4 text-right font-mono text-slate-500">{b.memory}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="text-xs text-slate-400 mt-2">Note: Current ~32s latency is dominated by Z-Image Turbo&apos;s 9-step diffusion loop, not Python overhead. The projected LibTorch numbers assume direct CUDA execution without Python/torch runtime dispatch.</p>
          </div>

          <div className="flex items-center gap-3 mb-6">
            <div className="bg-violet-100 p-3 rounded-2xl text-violet-600"><Search size={28} /></div>
            <div>
              <h3 className="font-bold text-xl text-slate-800">LoRA Search Benchmarks</h3>
              <p className="text-slate-500 text-sm font-medium">Semantic LoRA selection &mdash; keyword matching vs embedding similarity (gobed)</p>
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full bg-white rounded-2xl shadow-sm border border-slate-100 overflow-hidden">
              <thead className="bg-slate-50">
                <tr>
                  <th className="text-left px-6 py-4 font-bold text-slate-700">Engine</th>
                  <th className="text-right px-6 py-4 font-bold text-slate-700">Latency</th>
                  <th className="text-right px-6 py-4 font-bold text-slate-700">Accuracy</th>
                </tr>
              </thead>
              <tbody>
                {loraSearchBenchmarks.map((b, i) => (
                  <tr key={i} className={`border-t border-slate-100 ${i === 4 ? 'bg-violet-50' : ''}`}>
                    <td className="px-6 py-4 font-medium text-slate-800">{b.engine}</td>
                    <td className="px-6 py-4 text-right font-mono font-bold text-slate-700">{b.latency}</td>
                    <td className="px-6 py-4 text-right"><span className={`text-xs font-bold px-2 py-1 rounded ${
                      b.accuracy === 'Best' ? 'bg-green-100 text-green-700' :
                      b.accuracy === 'Excellent' ? 'bg-blue-100 text-blue-700' :
                      'bg-slate-100 text-slate-600'
                    }`}>{b.accuracy}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        {/* TurboQuant Ablations */}
        <section className="mb-20">
          <div className="flex items-center gap-3 mb-8">
            <div className="bg-yellow-100 p-3 rounded-2xl text-yellow-600"><Zap size={28} /></div>
            <div>
              <h2 className="font-fredoka text-3xl font-bold text-slate-800">TurboQuant Ablations</h2>
              <p className="text-slate-500 font-medium">MAE vs latency across quantization configs &mdash; 7 symbols, context=768</p>
            </div>
          </div>

          <div className="overflow-x-auto mb-8">
            <table className="w-full bg-white rounded-2xl shadow-sm border border-slate-100 overflow-hidden">
              <thead className="bg-slate-50">
                <tr>
                  <th className="text-left px-4 py-3 font-bold text-slate-700 text-sm">Config</th>
                  <th className="text-right px-4 py-3 font-bold text-slate-700 text-sm">Compression</th>
                  <th className="text-right px-4 py-3 font-bold text-slate-700 text-sm">H=16 Latency</th>
                  <th className="text-right px-4 py-3 font-bold text-slate-700 text-sm">H=16 MAE</th>
                  <th className="text-right px-4 py-3 font-bold text-slate-700 text-sm">H=64 Latency</th>
                  <th className="text-right px-4 py-3 font-bold text-slate-700 text-sm">H=64 MAE</th>
                  <th className="text-right px-4 py-3 font-bold text-slate-700 text-sm">H=128 Latency</th>
                  <th className="text-right px-4 py-3 font-bold text-slate-700 text-sm">H=128 MAE</th>
                </tr>
              </thead>
              <tbody className="text-sm">
                <tr className="border-t border-slate-100">
                  <td className="px-4 py-3 font-medium text-slate-800">Original PyTorch</td>
                  <td className="px-4 py-3 text-right font-mono text-slate-500">1.0x</td>
                  <td className="px-4 py-3 text-right font-mono">41.98 ms</td>
                  <td className="px-4 py-3 text-right font-mono">1645.1</td>
                  <td className="px-4 py-3 text-right font-mono">39.78 ms</td>
                  <td className="px-4 py-3 text-right font-mono">4768.5</td>
                  <td className="px-4 py-3 text-right font-mono">38.96 ms</td>
                  <td className="px-4 py-3 text-right font-mono">6497.4</td>
                </tr>
                <tr className="border-t border-slate-100">
                  <td className="px-4 py-3 font-medium text-slate-800">CuteChronos2 Eager</td>
                  <td className="px-4 py-3 text-right font-mono text-slate-500">1.0x</td>
                  <td className="px-4 py-3 text-right font-mono text-cyan-600 font-bold">19.15 ms</td>
                  <td className="px-4 py-3 text-right font-mono">970.8</td>
                  <td className="px-4 py-3 text-right font-mono text-cyan-600 font-bold">18.47 ms</td>
                  <td className="px-4 py-3 text-right font-mono">1496.3</td>
                  <td className="px-4 py-3 text-right font-mono text-cyan-600 font-bold">20.77 ms</td>
                  <td className="px-4 py-3 text-right font-mono">1441.1</td>
                </tr>
                <tr className="border-t border-slate-100 bg-cyan-50">
                  <td className="px-4 py-3 font-medium text-slate-800">CuteChronos2 Compiled</td>
                  <td className="px-4 py-3 text-right font-mono text-slate-500">1.0x</td>
                  <td className="px-4 py-3 text-right font-mono text-cyan-700 font-bold">1.55 ms</td>
                  <td className="px-4 py-3 text-right font-mono font-bold">943.4</td>
                  <td className="px-4 py-3 text-right font-mono text-cyan-700 font-bold">1.65 ms</td>
                  <td className="px-4 py-3 text-right font-mono font-bold">1499.7</td>
                  <td className="px-4 py-3 text-right font-mono text-cyan-700 font-bold">1.63 ms</td>
                  <td className="px-4 py-3 text-right font-mono font-bold">1461.0</td>
                </tr>
                <tr className="border-t border-slate-100">
                  <td className="px-4 py-3 font-medium text-slate-800">TQ4 (product+MSE)</td>
                  <td className="px-4 py-3 text-right font-mono text-yellow-600 font-bold">3.66x</td>
                  <td className="px-4 py-3 text-right font-mono">150.79 ms</td>
                  <td className="px-4 py-3 text-right font-mono">970.7</td>
                  <td className="px-4 py-3 text-right font-mono">124.96 ms</td>
                  <td className="px-4 py-3 text-right font-mono">1471.9</td>
                  <td className="px-4 py-3 text-right font-mono">123.35 ms</td>
                  <td className="px-4 py-3 text-right font-mono">1474.1</td>
                </tr>
                <tr className="border-t border-slate-100">
                  <td className="px-4 py-3 font-medium text-slate-800">TQ4 + Compiled</td>
                  <td className="px-4 py-3 text-right font-mono text-yellow-600 font-bold">3.66x</td>
                  <td className="px-4 py-3 text-right font-mono text-yellow-700 font-bold">16.40 ms</td>
                  <td className="px-4 py-3 text-right font-mono">966.1</td>
                  <td className="px-4 py-3 text-right font-mono text-yellow-700 font-bold">22.96 ms</td>
                  <td className="px-4 py-3 text-right font-mono">1498.0</td>
                  <td className="px-4 py-3 text-right font-mono text-yellow-700 font-bold">20.61 ms</td>
                  <td className="px-4 py-3 text-right font-mono">1467.0</td>
                </tr>
                <tr className="border-t border-slate-100">
                  <td className="px-4 py-3 font-medium text-slate-800">TQ3 (product+MSE)</td>
                  <td className="px-4 py-3 text-right font-mono text-yellow-600 font-bold">4.74x</td>
                  <td className="px-4 py-3 text-right font-mono">346.47 ms</td>
                  <td className="px-4 py-3 text-right font-mono">981.8</td>
                  <td className="px-4 py-3 text-right font-mono">343.58 ms</td>
                  <td className="px-4 py-3 text-right font-mono">1665.1</td>
                  <td className="px-4 py-3 text-right font-mono">344.55 ms</td>
                  <td className="px-4 py-3 text-right font-mono">2045.3</td>
                </tr>
              </tbody>
            </table>
          </div>

          <h3 className="font-bold text-xl text-slate-800 mb-4">Rolling Forecast Ablation (448 windows)</h3>
          <div className="overflow-x-auto">
            <table className="w-full bg-white rounded-2xl shadow-sm border border-slate-100 overflow-hidden">
              <thead className="bg-slate-50">
                <tr>
                  <th className="text-left px-5 py-3 font-bold text-slate-700 text-sm">Config</th>
                  <th className="text-right px-5 py-3 font-bold text-slate-700 text-sm">Sequential Total</th>
                  <th className="text-right px-5 py-3 font-bold text-slate-700 text-sm">Per Window</th>
                  <th className="text-right px-5 py-3 font-bold text-slate-700 text-sm">Batched Total</th>
                  <th className="text-right px-5 py-3 font-bold text-slate-700 text-sm">Batched/Window</th>
                  <th className="text-right px-5 py-3 font-bold text-slate-700 text-sm">MAE</th>
                </tr>
              </thead>
              <tbody className="text-sm">
                <tr className="border-t border-slate-100">
                  <td className="px-5 py-3 font-medium text-slate-800">Original PyTorch</td>
                  <td className="px-5 py-3 text-right font-mono">18,041 ms</td>
                  <td className="px-5 py-3 text-right font-mono">40.27 ms</td>
                  <td className="px-5 py-3 text-right font-mono text-slate-400">N/A</td>
                  <td className="px-5 py-3 text-right font-mono text-slate-400">N/A</td>
                  <td className="px-5 py-3 text-right font-mono">4263.2</td>
                </tr>
                <tr className="border-t border-slate-100">
                  <td className="px-5 py-3 font-medium text-slate-800">CuteChronos2 Eager</td>
                  <td className="px-5 py-3 text-right font-mono">11,439 ms</td>
                  <td className="px-5 py-3 text-right font-mono">25.53 ms</td>
                  <td className="px-5 py-3 text-right font-mono text-cyan-600 font-bold">400.6 ms</td>
                  <td className="px-5 py-3 text-right font-mono text-cyan-600 font-bold">0.89 ms</td>
                  <td className="px-5 py-3 text-right font-mono">317.8</td>
                </tr>
                <tr className="border-t border-slate-100 bg-cyan-50">
                  <td className="px-5 py-3 font-medium text-slate-800">CuteChronos2 Compiled</td>
                  <td className="px-5 py-3 text-right font-mono text-cyan-700 font-bold">753.2 ms</td>
                  <td className="px-5 py-3 text-right font-mono text-cyan-700 font-bold">1.68 ms</td>
                  <td className="px-5 py-3 text-right font-mono text-cyan-700 font-bold">52.3 ms</td>
                  <td className="px-5 py-3 text-right font-mono text-cyan-700 font-bold">0.117 ms</td>
                  <td className="px-5 py-3 text-right font-mono font-bold">317.2</td>
                </tr>
                <tr className="border-t border-slate-100">
                  <td className="px-5 py-3 font-medium text-slate-800">TQ4 + Compiled</td>
                  <td className="px-5 py-3 text-right font-mono">9,312 ms</td>
                  <td className="px-5 py-3 text-right font-mono">20.78 ms</td>
                  <td className="px-5 py-3 text-right font-mono">417.3 ms</td>
                  <td className="px-5 py-3 text-right font-mono">0.93 ms</td>
                  <td className="px-5 py-3 text-right font-mono">320.2</td>
                </tr>
              </tbody>
            </table>
            <p className="text-xs text-slate-400 mt-2">Rolling forecast: 448 sequential 1-step predictions over 7 crypto/equity symbols (BTC, ETH, SOL, TSLA, AAPL, NVDA, LINK)</p>
          </div>
        </section>

        {/* Acceleration Techniques */}
        <section className="mb-20">
          <div className="flex items-center gap-3 mb-8">
            <div className="bg-purple-100 p-3 rounded-2xl text-purple-600"><Zap size={28} /></div>
            <div>
              <h2 className="font-fredoka text-3xl font-bold text-slate-800">Acceleration Techniques</h2>
              <p className="text-slate-500 font-medium">Everything we&apos;re building, researching, and shipping to make models faster</p>
            </div>
          </div>

          <div className="space-y-6">
            {accelerationTechniques.map((t, i) => (
              <div key={i} className="bg-white p-8 rounded-2xl border border-slate-100 shadow-sm">
                <div className="flex items-start justify-between mb-4">
                  <div>
                    <h3 className="font-fredoka text-2xl font-bold text-slate-800">{t.name}</h3>
                    <code className="text-xs bg-slate-100 px-2 py-1 rounded text-slate-500">{t.module}</code>
                  </div>
                  <span className={`text-xs font-bold px-3 py-1 rounded-full ${
                    t.status === 'Production' ? 'bg-green-100 text-green-700' :
                    t.status === 'Research' ? 'bg-yellow-100 text-yellow-700' :
                    'bg-slate-100 text-slate-500'
                  }`}>{t.status}</span>
                </div>
                <p className="text-slate-600 mb-4">{t.description}</p>
                <div className="flex flex-wrap gap-2">
                  {t.techniques.map((tech, j) => (
                    <span key={j} className="text-xs bg-slate-50 border border-slate-200 px-3 py-1 rounded-full text-slate-600 font-medium">{tech}</span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* Architecture Overview */}
        <section>
          <div className="flex items-center gap-3 mb-8">
            <div className="bg-indigo-100 p-3 rounded-2xl text-indigo-600"><Cpu size={28} /></div>
            <div>
              <h2 className="font-fredoka text-3xl font-bold text-slate-800">Model Architectures</h2>
              <p className="text-slate-500 font-medium">Internal structure of the models we accelerate</p>
            </div>
          </div>

          <div className="grid md:grid-cols-2 gap-6">
            <div className="bg-white p-6 rounded-2xl border border-slate-100 shadow-sm">
              <h3 className="font-bold text-lg text-slate-800 mb-4 flex items-center gap-2"><LineChart size={18} className="text-cyan-500" /> CuteChronos2 Pipeline</h3>
              <div className="space-y-2 text-sm font-mono text-slate-600">
                <div className="bg-slate-50 px-3 py-2 rounded">Input &rarr; InstanceNorm &rarr; Patching</div>
                <div className="bg-slate-50 px-3 py-2 rounded">&rarr; InputPatchEmbedding</div>
                <div className="bg-cyan-50 px-3 py-2 rounded border border-cyan-200">&rarr; [EncoderBlock &times; 12]</div>
                <div className="bg-slate-50 px-3 py-2 rounded text-xs pl-6">TimeSelfAttention (RoPE) + GroupSelfAttention + FeedForward</div>
                <div className="bg-slate-50 px-3 py-2 rounded">&rarr; FinalLayerNorm &rarr; OutputPatchEmbedding</div>
                <div className="bg-slate-50 px-3 py-2 rounded">&rarr; Inverse InstanceNorm &rarr; Quantile Predictions</div>
              </div>
            </div>

            <div className="bg-white p-6 rounded-2xl border border-slate-100 shadow-sm">
              <h3 className="font-bold text-lg text-slate-800 mb-4 flex items-center gap-2"><ImageIcon size={18} className="text-pink-500" /> CuteZImage Transformer</h3>
              <div className="space-y-2 text-sm font-mono text-slate-600">
                <div className="bg-slate-50 px-3 py-2 rounded">Text Encoding &rarr; Timestep Embed &rarr; Patch Embed</div>
                <div className="bg-pink-50 px-3 py-2 rounded border border-pink-200">&rarr; [TransformerBlock &times; 30]</div>
                <div className="bg-slate-50 px-3 py-2 rounded text-xs pl-6">AdaLN + Attention (Complex RoPE) + SiLU-Gated FFN</div>
                <div className="bg-pink-50 px-3 py-2 rounded border border-pink-200">&rarr; [RefinerBlock &times; 2]</div>
                <div className="bg-slate-50 px-3 py-2 rounded">&rarr; Final Norm &rarr; Unpatchify &rarr; VAE Decode</div>
              </div>
            </div>
          </div>
        </section>
      </main>

      {/* Footer */}
      <footer className="bg-white/90 border-t border-pink-200 py-8">
        <div className="max-w-7xl mx-auto px-6 flex justify-between items-center">
          <p className="text-slate-400 text-sm">&copy; 2026 <a href="https://app.nz" target="_blank" rel="noopener noreferrer" className="hover:text-indigo-500">Applied Science Company</a></p>
          <div className="flex gap-4 text-sm font-bold">
            <Link href="/" className="text-slate-500 hover:text-pink-500">Home</Link>
            <Link href="/blog" className="text-slate-500 hover:text-purple-500">Blog</Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
