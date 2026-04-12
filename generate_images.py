#!/usr/bin/env python3
"""Generate all CuteDSL site images using FAL Flux Schnell, convert to webp q85, upload to R2."""
import requests
import subprocess
import os
import sys
import time

FAL_KEY = "a0d7afb7-0810-4f68-80b6-3058788523fb:5e7edd54adf40b5abba84f53e68ef7be"
FAL_URL = "https://queue.fal.run/fal-ai/flux/schnell"
OUT_DIR = "/nvme0n1-disk/code/cutedsl-site/frontend/public/images"
R2_ENDPOINT = "https://f76d25b8b86cfa5638f43016510d8f77.r2.cloudflarestorage.com"
R2_BUCKET = "appstatic"
R2_PATH = "cutedsl/images"

HEADERS = {
    "Authorization": f"Key {FAL_KEY}",
    "Content-Type": "application/json",
}

# FAL image sizes: square_hd (1024x1024), landscape_16_9 (1360x768), landscape_4_3 (1152x768), portrait_4_3 (768x1152), portrait_16_9 (768x1360)
IMAGES = [
    {
        "name": "og-image",
        "prompt": "cute anime fairy girl with pink butterfly wings, brown hair with flowers, blue eyes, sitting at a glowing computer terminal with holographic AI neural network visualizations floating around her, soft pink and purple lighting, dreamy forest tech lab, high quality digital art, fantasy illustration",
        "size": "landscape_16_9",
    },
    {
        "name": "hero",
        "prompt": "cute anime fairy girl with delicate pink butterfly wings and flower crown, brown hair, blue eyes, holding a glowing magical wand casting sparkles and code symbols, surrounded by floating holographic AI model diagrams and neural network nodes, soft ethereal pink purple blue lighting, enchanted forest clearing, high quality fantasy digital art illustration",
        "size": "square_hd",
    },
    {
        "name": "bg-1",
        "prompt": "dreamy enchanted forest landscape with soft pink cherry blossom trees, floating sparkles and magical particles, gentle stream with glowing reflections, pastel pink purple and cyan color palette, ethereal misty atmosphere, no people, landscape scenery, high quality digital painting, anime background art",
        "size": "landscape_16_9",
    },
    {
        "name": "bg-2",
        "prompt": "futuristic cute pastel laboratory with holographic screens showing AI neural networks and code, pink and purple neon glow, floating data particles, soft ambient lighting, cozy tech workspace with plants and crystals, no people, landscape scenery, high quality digital art, anime background",
        "size": "landscape_16_9",
    },
    {
        "name": "bg-3",
        "prompt": "magical sunset sky over a crystalline city with floating platforms and glowing pathways, aurora borealis in soft pink purple and cyan, scattered cherry blossom petals drifting through the air, dreamy atmosphere, no people, landscape scenery, high quality fantasy digital art, anime background",
        "size": "landscape_16_9",
    },
    {
        "name": "bg-4",
        "prompt": "abstract magical technology background with flowing streams of glowing pink and cyan data particles forming neural network patterns, soft bokeh lights, gradient from deep purple to soft pink, ethereal and dreamy, no people, abstract digital art, high quality anime style background",
        "size": "landscape_16_9",
    },
    {
        "name": "training",
        "prompt": "cute anime fairy girl with pink wings studying holographic screens showing training loss curves and model architecture diagrams, cozy magical workshop filled with glowing crystals and floating books, warm pink and purple ambient lighting, high quality fantasy digital art illustration",
        "size": "landscape_16_9",
    },
    {
        "name": "avatar",
        "prompt": "cute anime fairy girl portrait closeup, pink butterfly wings, brown hair with pink flower, blue eyes, gentle smile, soft glowing pink aura, simple clean pastel background, high quality digital art portrait, fantasy illustration",
        "size": "square_hd",
    },
    {
        "name": "token-bg",
        "prompt": "dark cosmic space background with golden coins and stars scattered across a deep purple nebula, glowing constellation patterns forming blockchain nodes connected by light beams, sparkles and stardust, no people, abstract cosmic digital art, high quality, anime style",
        "size": "landscape_16_9",
    },
]

os.makedirs(OUT_DIR, exist_ok=True)


def submit_fal(prompt, size):
    """Submit a generation request to FAL queue."""
    resp = requests.post(
        FAL_URL,
        headers=HEADERS,
        json={
            "prompt": prompt,
            "image_size": size,
            "num_inference_steps": 4,
            "enable_safety_checker": False,
        },
        timeout=30,
    )
    data = resp.json()
    return data.get("request_id"), data.get("response_url"), data.get("status_url")


def poll_fal(status_url, response_url, timeout=120):
    """Poll FAL queue until complete."""
    start = time.time()
    while time.time() - start < timeout:
        resp = requests.get(status_url, headers=HEADERS, timeout=30)
        data = resp.json()
        status = data.get("status")
        if status == "COMPLETED":
            # Fetch the result
            result = requests.get(response_url, headers=HEADERS, timeout=30)
            return result.json()
        if status in ("FAILED", "CANCELLED"):
            return None
        time.sleep(1.5)
    return None


def generate_image(img):
    """Generate a single image via FAL."""
    name = img["name"]
    print(f"  Submitting {name}...")

    request_id, response_url, status_url = submit_fal(img["prompt"], img["size"])
    if not request_id:
        print(f"  ERROR {name}: Failed to submit")
        return None

    print(f"  Polling {name} (id: {request_id[:12]}...)...")
    result = poll_fal(status_url, response_url)
    if not result or not result.get("images"):
        print(f"  ERROR {name}: Generation failed")
        return None

    image_url = result["images"][0]["url"]
    print(f"  Downloading {name}...")

    # Download image
    img_resp = requests.get(image_url, timeout=60)
    raw_path = os.path.join(OUT_DIR, f"{name}_raw.png")
    with open(raw_path, "wb") as f:
        f.write(img_resp.content)

    # Convert to webp q85
    webp_path = os.path.join(OUT_DIR, f"{name}.webp")
    subprocess.run(
        ["cwebp", "-q", "85", raw_path, "-o", webp_path],
        check=True,
        capture_output=True,
    )
    os.remove(raw_path)

    size_kb = os.path.getsize(webp_path) / 1024
    print(f"  OK {name}.webp ({size_kb:.0f} KB)")
    return webp_path


def convert_logo():
    """Convert the existing cutedsl.png logo to webp."""
    src = "/nvme0n1-disk/code/cutedsl/cutedsl.png"
    dst = os.path.join(OUT_DIR, "logo.webp")
    subprocess.run(
        ["cwebp", "-q", "85", src, "-o", dst],
        check=True,
        capture_output=True,
    )
    size_kb = os.path.getsize(dst) / 1024
    print(f"  OK logo.webp ({size_kb:.0f} KB)")
    return dst


def upload_to_r2():
    """Upload all webp images to R2 bucket."""
    print("\nUploading to R2...")
    cmd = [
        "aws", "s3", "sync",
        OUT_DIR,
        f"s3://{R2_BUCKET}/{R2_PATH}/",
        "--endpoint-url", R2_ENDPOINT,
        "--exclude", "*",
        "--include", "*.webp",
        "--content-type", "image/webp",
        "--cache-control", "public, max-age=31536000, immutable",
        "--size-only",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    print(result.stdout)
    if result.returncode != 0:
        print(f"Upload error: {result.stderr}")
    else:
        print("Upload complete!")


if __name__ == "__main__":
    print("=== CuteDSL Image Generation (FAL Flux Schnell) ===\n")

    # Check for cwebp
    if subprocess.run(["which", "cwebp"], capture_output=True).returncode != 0:
        print("ERROR: cwebp not found. Install with: apt install webp")
        sys.exit(1)

    # Convert logo
    print("[1] Converting logo...")
    convert_logo()

    # Generate all images
    print(f"\n[2] Generating {len(IMAGES)} images via FAL Flux Schnell...")
    for img in IMAGES:
        retries = 2
        for attempt in range(retries):
            result = generate_image(img)
            if result:
                break
            if attempt < retries - 1:
                print(f"  Retrying {img['name']}...")
                time.sleep(2)

    # Upload
    print("\n[3] Uploading to R2...")
    upload_to_r2()

    # List results
    print("\n=== Generated Images ===")
    for f in sorted(os.listdir(OUT_DIR)):
        if f.endswith(".webp"):
            size = os.path.getsize(os.path.join(OUT_DIR, f)) / 1024
            print(f"  https://appstatic.app.nz/{R2_PATH}/{f}  ({size:.0f} KB)")
