export type StudioAdjustments = {
  exposure: number;
  brightness: number;
  contrast: number;
  highlights: number;
  shadows: number;
  shadowHue: number;
  midtoneHue: number;
  highlightHue: number;
  saturation: number;
  temperature: number;
  tint: number;
  fade: number;
  vignette: number;
  grain: number;
};

export const DEFAULT_ADJUSTMENTS: StudioAdjustments = {
  exposure: 0,
  brightness: 0,
  contrast: 0,
  highlights: 0,
  shadows: 0,
  shadowHue: 0,
  midtoneHue: 0,
  highlightHue: 0,
  saturation: 0,
  temperature: 0,
  tint: 0,
  fade: 0,
  vignette: 0,
  grain: 0,
};

const VERTEX = `#version 300 es
in vec2 a_position;
in vec2 a_texCoord;
out vec2 v_texCoord;
void main() {
  gl_Position = vec4(a_position, 0.0, 1.0);
  v_texCoord = a_texCoord;
}`;

const FRAGMENT = `#version 300 es
precision highp float;
uniform sampler2D u_image;
uniform vec2 u_resolution;
uniform float u_exposure;
uniform float u_brightness;
uniform float u_contrast;
uniform float u_highlights;
uniform float u_shadows;
uniform float u_shadowHue;
uniform float u_midtoneHue;
uniform float u_highlightHue;
uniform float u_saturation;
uniform float u_temperature;
uniform float u_tint;
uniform float u_fade;
uniform float u_vignette;
uniform float u_grain;
uniform float u_seed;
uniform float u_fxaa;
in vec2 v_texCoord;
out vec4 outColor;

float random(vec2 p) {
  return fract(sin(dot(p, vec2(12.9898, 78.233)) + u_seed) * 43758.5453);
}

vec3 rgbToHsv(vec3 color) {
  vec4 k = vec4(0.0, -1.0 / 3.0, 2.0 / 3.0, -1.0);
  vec4 p = mix(vec4(color.bg, k.wz), vec4(color.gb, k.xy), step(color.b, color.g));
  vec4 q = mix(vec4(p.xyw, color.r), vec4(color.r, p.yzx), step(p.x, color.r));
  float d = q.x - min(q.w, q.y);
  float e = 1.0e-10;
  return vec3(abs(q.z + (q.w - q.y) / (6.0 * d + e)), d / (q.x + e), q.x);
}

vec3 hsvToRgb(vec3 color) {
  vec3 p = abs(fract(color.xxx + vec3(0.0, 2.0 / 3.0, 1.0 / 3.0)) * 6.0 - 3.0);
  return color.z * mix(vec3(1.0), clamp(p - 1.0, 0.0, 1.0), color.y);
}

vec3 shiftHue(vec3 color, float degrees, float amount) {
  vec3 hsv = rgbToHsv(max(color, 0.0));
  hsv.x = fract(hsv.x + degrees / 360.0);
  return mix(color, hsvToRgb(hsv), amount);
}

// A compact FXAA variant for the final export pass. It only blends pixels
// that sit on a high-contrast diagonal edge, preserving flat areas and detail
// in the source image while taking the stair-step edge off rotated glyphs.
vec4 antiAlias(sampler2D image, vec2 uv) {
  vec2 pixel = 1.0 / u_resolution;
  vec4 center = texture(image, uv);
  vec3 northWest = texture(image, uv + vec2(-1.0, -1.0) * pixel).rgb;
  vec3 northEast = texture(image, uv + vec2(1.0, -1.0) * pixel).rgb;
  vec3 southWest = texture(image, uv + vec2(-1.0, 1.0) * pixel).rgb;
  vec3 southEast = texture(image, uv + vec2(1.0, 1.0) * pixel).rgb;
  float lumaCenter = dot(center.rgb, vec3(0.299, 0.587, 0.114));
  float lumaNW = dot(northWest, vec3(0.299, 0.587, 0.114));
  float lumaNE = dot(northEast, vec3(0.299, 0.587, 0.114));
  float lumaSW = dot(southWest, vec3(0.299, 0.587, 0.114));
  float lumaSE = dot(southEast, vec3(0.299, 0.587, 0.114));
  float lumaMin = min(lumaCenter, min(min(lumaNW, lumaNE), min(lumaSW, lumaSE)));
  float lumaMax = max(lumaCenter, max(max(lumaNW, lumaNE), max(lumaSW, lumaSE)));
  if (lumaMax - lumaMin < max(0.0312, lumaMax * 0.125)) return center;
  vec2 direction = vec2(-((lumaNW + lumaNE) - (lumaSW + lumaSE)), (lumaNW + lumaSW) - (lumaNE + lumaSE));
  float reduce = max((lumaNW + lumaNE + lumaSW + lumaSE) * 0.03125, 0.0078125);
  float inverseDirection = 1.0 / (min(abs(direction.x), abs(direction.y)) + reduce);
  direction = clamp(direction * inverseDirection, vec2(-8.0), vec2(8.0)) * pixel;
  vec4 blendA = 0.5 * (texture(image, uv + direction * (1.0 / 3.0 - 0.5)) + texture(image, uv + direction * (2.0 / 3.0 - 0.5)));
  vec4 blendB = blendA * 0.5 + 0.25 * (texture(image, uv + direction * -0.5) + texture(image, uv + direction * 0.5));
  float blendLuma = dot(blendB.rgb, vec3(0.299, 0.587, 0.114));
  return blendLuma < lumaMin || blendLuma > lumaMax ? blendA : blendB;
}

void main() {
  vec4 sampleColor = u_fxaa > 0.5 ? antiAlias(u_image, v_texCoord) : texture(u_image, v_texCoord);
  vec3 color = sampleColor.rgb * exp2(u_exposure);
  color += u_brightness;
  color = (color - 0.5) * (1.0 + u_contrast) + 0.5;

  float luma = dot(color, vec3(0.2126, 0.7152, 0.0722));
  float shadowMask = 1.0 - smoothstep(0.05, 0.62, luma);
  float highlightMask = smoothstep(0.38, 0.95, luma);
  float midtoneMask = clamp(1.0 - shadowMask - highlightMask, 0.0, 1.0);
  color += u_shadows * shadowMask * 0.45;
  color += u_highlights * highlightMask * 0.45;
  color = shiftHue(color, u_shadowHue, shadowMask);
  color = shiftHue(color, u_midtoneHue, midtoneMask);
  color = shiftHue(color, u_highlightHue, highlightMask);

  luma = dot(color, vec3(0.2126, 0.7152, 0.0722));
  color = mix(vec3(luma), color, 1.0 + u_saturation);
  color.r += u_temperature * 0.09;
  color.b -= u_temperature * 0.09;
  color.g += u_tint * 0.06;
  color = mix(color, vec3(0.5), u_fade * 0.22);

  vec2 uv = v_texCoord - 0.5;
  float edge = smoothstep(0.2, 0.72, length(uv));
  color *= 1.0 - edge * u_vignette * 0.78;
  color += (random(gl_FragCoord.xy) - 0.5) * u_grain * 0.12;
  outColor = vec4(clamp(color, 0.0, 1.0), sampleColor.a);
}`;

function makeShader(gl: WebGL2RenderingContext, type: number, source: string) {
  const shader = gl.createShader(type);
  if (!shader) throw new Error('Unable to create WebGL shader');
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    throw new Error(gl.getShaderInfoLog(shader) || 'Shader compilation failed');
  }
  return shader;
}

export class StudioRenderer {
  private gl: WebGL2RenderingContext;
  private program: WebGLProgram;
  private texture: WebGLTexture;
  private uniforms: Record<string, WebGLUniformLocation | null>;
  private textureWidth = 0;
  private textureHeight = 0;

  constructor(public readonly canvas: HTMLCanvasElement, options: { preserveDrawingBuffer?: boolean } = {}) {
    const gl = canvas.getContext('webgl2', {
      alpha: true,
      antialias: false,
      // Export draws this WebGL canvas into a separate 2D encoder canvas. In
      // that path the default transient framebuffer can be discarded before
      // drawImage reads it, producing a valid but entirely black video.
      preserveDrawingBuffer: options.preserveDrawingBuffer ?? false,
      premultipliedAlpha: false,
      powerPreference: 'high-performance',
    });
    if (!gl) throw new Error('WebGL 2 is required for Studio');
    this.gl = gl;
    const program = gl.createProgram();
    if (!program) throw new Error('Unable to create WebGL program');
    gl.attachShader(program, makeShader(gl, gl.VERTEX_SHADER, VERTEX));
    gl.attachShader(program, makeShader(gl, gl.FRAGMENT_SHADER, FRAGMENT));
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
      throw new Error(gl.getProgramInfoLog(program) || 'Shader linking failed');
    }
    this.program = program;

    const vao = gl.createVertexArray();
    gl.bindVertexArray(vao);
    const positionBuffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, positionBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1]), gl.STATIC_DRAW);
    const position = gl.getAttribLocation(program, 'a_position');
    gl.enableVertexAttribArray(position);
    gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 0, 0);

    const texBuffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, texBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([0, 1, 1, 1, 0, 0, 0, 0, 1, 1, 1, 0]), gl.STATIC_DRAW);
    const texCoord = gl.getAttribLocation(program, 'a_texCoord');
    gl.enableVertexAttribArray(texCoord);
    gl.vertexAttribPointer(texCoord, 2, gl.FLOAT, false, 0, 0);

    const texture = gl.createTexture();
    if (!texture) throw new Error('Unable to create WebGL texture');
    this.texture = texture;
    gl.bindTexture(gl.TEXTURE_2D, texture);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.useProgram(program);

    const names = ['exposure', 'brightness', 'contrast', 'highlights', 'shadows', 'shadowHue', 'midtoneHue', 'highlightHue', 'saturation', 'temperature', 'tint', 'fade', 'vignette', 'grain', 'seed', 'fxaa'];
    this.uniforms = Object.fromEntries(names.map((name) => [name, gl.getUniformLocation(program, `u_${name}`)]));
    this.uniforms.resolution = gl.getUniformLocation(program, 'u_resolution');
  }

  diagnostics() {
    const debug = this.gl.getExtension('WEBGL_debug_renderer_info');
    return {
      api: 'webgl2' as const,
      renderer: String(debug ? this.gl.getParameter(debug.UNMASKED_RENDERER_WEBGL) : this.gl.getParameter(this.gl.RENDERER)),
      vendor: String(debug ? this.gl.getParameter(debug.UNMASKED_VENDOR_WEBGL) : this.gl.getParameter(this.gl.VENDOR)),
      maxTextureSize: Number(this.gl.getParameter(this.gl.MAX_TEXTURE_SIZE)),
      powerPreference: 'high-performance' as const,
    };
  }

  resize(width: number, height: number) {
    const safeWidth = Math.max(2, Math.round(width / 2) * 2);
    const safeHeight = Math.max(2, Math.round(height / 2) * 2);
    if (this.canvas.width !== safeWidth) this.canvas.width = safeWidth;
    if (this.canvas.height !== safeHeight) this.canvas.height = safeHeight;
  }

  draw(source: TexImageSource, adjustments: StudioAdjustments, seed = 0, options: { fxaa?: boolean } = {}) {
    const { gl } = this;
    gl.viewport(0, 0, this.canvas.width, this.canvas.height);
    gl.useProgram(this.program);
    gl.bindTexture(gl.TEXTURE_2D, this.texture);
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, 0);
    const dimensions = source instanceof HTMLVideoElement
      ? [source.videoWidth, source.videoHeight]
      : source instanceof HTMLImageElement
        ? [source.naturalWidth, source.naturalHeight]
        : 'displayWidth' in source && 'displayHeight' in source
          ? [Number(source.displayWidth), Number(source.displayHeight)]
          : ['width' in source && 'height' in source ? Number(source.width) : 0, 'width' in source && 'height' in source ? Number(source.height) : 0];
    if (dimensions[0] !== this.textureWidth || dimensions[1] !== this.textureHeight) {
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, source);
      this.textureWidth = dimensions[0];
      this.textureHeight = dimensions[1];
    } else {
      gl.texSubImage2D(gl.TEXTURE_2D, 0, 0, 0, gl.RGBA, gl.UNSIGNED_BYTE, source);
    }
    gl.uniform2f(this.uniforms.resolution, this.canvas.width, this.canvas.height);
    (Object.keys(DEFAULT_ADJUSTMENTS) as (keyof StudioAdjustments)[]).forEach((key) => {
      gl.uniform1f(this.uniforms[key], adjustments[key]);
    });
    gl.uniform1f(this.uniforms.seed, seed);
    gl.uniform1f(this.uniforms.fxaa, options.fxaa ? 1 : 0);
    gl.drawArrays(gl.TRIANGLES, 0, 6);
  }

  destroy() {
    this.gl.deleteTexture(this.texture);
    this.gl.deleteProgram(this.program);
  }
}
